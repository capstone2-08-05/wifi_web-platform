"""Grid-based AP 최적 위치 추천.

입력받은 BBox 내를 step_m 간격으로 순회하며 고속 path-loss 모델로
신호 품질 점수를 산정, 가장 높은 점수의 격자 좌표를 반환한다.

Score 계산 규칙 (수신 포인트 하나당):
  - pred RSSI < shadow_threshold_dbm → -shadow_penalty (음영 패널티)
  - pred RSSI ≥ shadow_threshold_dbm → +pred_rssi (신호 세기 가점)
"""
from __future__ import annotations

import logging
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
from app.models.scene_version import SceneVersion
from app.models.project import Project
from app.models.user import User
from app.schemas.rf.ap_recommendation import ApRecommendationItem, ApRecommendationRequest, ApRecommendationResponse
from app.services.rf.calibration_worker.path_loss import (
    AccessPoint,
    CalibrationParams,
    Measurement,
    WallSegment,
    predict_rssi_best_ap,
)

logger = logging.getLogger(__name__)

# 평가 수신 포인트 생성용 해상도 (미터) — 너무 촘촘하면 느림, 너무 성글면 부정확
_EVAL_GRID_STEP_M = 1.0
# 최소 후보점 수 확보 — 영역이 너무 작으면 step 자동 축소
_MIN_CANDIDATES = 4


def recommend_ap_location(
    db: Session,
    request: ApRecommendationRequest,
    current_user: User,
) -> ApRecommendationResponse:
    """BBox 내 Grid Search로 최적 AP 위치 반환."""
    # 1) scene_version 권한 확인
    sv = db.execute(
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(request.scene_version_id),
            Project.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if sv is None:
        raise AppError(ErrorCode.SCENE_VERSION_NOT_FOUND, "Scene version not found.", 404)

    # 2) 벽 데이터 로드
    walls = _load_walls(db, str(sv.id))

    # 3) 보정 파라미터 로드 (없으면 기본값)
    params = _load_calibration_params(db, str(sv.id), request.calibration_run_id)

    # 4) 기존 AP 변환
    existing_aps = _parse_existing_aps(request.existing_aps)

    # 5) 탐색 후보 격자 생성
    candidates = _generate_candidates(
        request.x_min, request.x_max,
        request.y_min, request.y_max,
        request.step_m,
    )
    if not candidates:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "BBox가 너무 작아 후보 격자를 생성할 수 없습니다. "
            "영역을 넓히거나 step_m을 줄여주세요.",
            400,
        )

    # 6) 평가 수신 포인트 격자 생성 (도면 전체 기준)
    eval_points = _generate_eval_points(db, str(sv.id))
    if not eval_points:
        # 벽/도면 정보 없으면 BBox 자체를 eval 격자로 사용
        eval_points = _generate_candidates(
            request.x_min, request.x_max,
            request.y_min, request.y_max,
            _EVAL_GRID_STEP_M,
        )

    logger.info(
        "AP 추천 시작: scene=%s candidates=%d eval_points=%d existing_aps=%d",
        sv.id, len(candidates), len(eval_points), len(existing_aps),
    )

    # 7) Grid Search — 상위 n_recommendations개 반환
    top_results = _grid_search_topn(
        candidates=candidates,
        eval_points=eval_points,
        existing_aps=existing_aps,
        walls=walls,
        params=params,
        shadow_threshold_dbm=request.shadow_threshold_dbm,
        shadow_penalty=request.shadow_penalty,
        n=request.n_recommendations,
    )

    logger.info(
        "AP 추천 완료: top%d, best=(%.2f, %.2f) score=%.1f",
        len(top_results), top_results[0][0], top_results[0][1], top_results[0][2],
    )

    return ApRecommendationResponse(
        recommendations=[
            ApRecommendationItem(
                rank=i + 1,
                recommended_x=round(x, 3),
                recommended_y=round(y, 3),
                score=round(score, 2),
            )
            for i, (x, y, score) in enumerate(top_results)
        ],
        candidates_evaluated=len(candidates),
    )


# ────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ────────────────────────────────────────────────────────────────────

def _generate_candidates(
    x_min: float, x_max: float,
    y_min: float, y_max: float,
    step_m: float,
) -> list[tuple[float, float]]:
    """BBox 내부를 step_m 간격으로 순회하는 격자 좌표 리스트."""
    if x_max <= x_min or y_max <= y_min:
        return []
    pts: list[tuple[float, float]] = []
    x = x_min
    while x <= x_max + 1e-9:
        y = y_min
        while y <= y_max + 1e-9:
            pts.append((x, y))
            y = round(y + step_m, 6)
        x = round(x + step_m, 6)
    return pts


def _generate_eval_points(
    db: Session, scene_version_id: str,
) -> list[Measurement]:
    """confirmed scene version 의 벽 bbox 기반으로 평가 격자를 만든다.

    벽이 없으면 빈 리스트 반환 — 호출측이 BBox fallback 사용.
    """
    from app.models.wall import Wall

    rows = db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all()
    if not rows:
        return []

    xs: list[float] = []
    ys: list[float] = []
    for w in rows:
        gj = wkb_to_geojson(w.centerline_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        for coord in (gj.get("coordinates") or []):
            xs.append(float(coord[0]))
            ys.append(float(coord[1]))
    if not xs:
        return []

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    pts: list[Measurement] = []
    x = min_x
    while x <= max_x + 1e-9:
        y = min_y
        while y <= max_y + 1e-9:
            pts.append(Measurement(x=x, y=y, rssi_dbm=0.0))
            y = round(y + _EVAL_GRID_STEP_M, 6)
        x = round(x + _EVAL_GRID_STEP_M, 6)
    return pts


def _load_walls(db: Session, scene_version_id: str) -> list[WallSegment]:
    from app.models.wall import Wall

    rows = db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all()
    out: list[WallSegment] = []
    for w in rows:
        gj = wkb_to_geojson(w.centerline_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        coords = gj.get("coordinates") or []
        if len(coords) < 2:
            continue
        x1, y1 = float(coords[0][0]), float(coords[0][1])
        x2, y2 = float(coords[-1][0]), float(coords[-1][1])
        out.append(WallSegment(
            x1=x1, y1=y1, x2=x2, y2=y2,
            thickness_m=float(w.thickness_m) if w.thickness_m is not None else 0.12,
            material=(w.material_label or "").lower() or None,
        ))
    return out


def _load_calibration_params(
    db: Session, scene_version_id: str, calibration_run_id=None
) -> CalibrationParams:
    """calibration_run_id 지정 시 해당 run의 best_params 사용.
    없으면 scene_version 의 최신 completed calibration 자동 탐색.
    둘 다 없으면 기본값 반환.
    """
    from app.services.rf.calibration_worker.apply import get_latest_calibration
    from app.models.calibration_run import CalibrationRun

    run = None
    if calibration_run_id is not None:
        run = db.get(CalibrationRun, str(calibration_run_id))
    if run is None:
        run = get_latest_calibration(db, scene_version_id)
    if run is None or not run.metrics_json:
        return CalibrationParams()

    best = (run.metrics_json or {}).get("best_params") or {}
    if not best:
        return CalibrationParams()

    return CalibrationParams(
        tx_power_offset_db=float(best.get("tx_power_offset_db", 0.0)),
        path_loss_exp=float(best.get("path_loss_exp", 3.0)),
        floor_thickness_m=float(best.get("floor_thickness_m", 0.10)),
        furniture_default_thickness_m=float(best.get("furniture_default_thickness_m", 0.05)),
        material_attenuation_scales={
            str(k): float(v)
            for k, v in (best.get("material_attenuation_scales") or {}).items()
        },
    )


def _parse_existing_aps(raw: list[dict]) -> list[AccessPoint]:
    aps: list[AccessPoint] = []
    for i, ap in enumerate(raw):
        x = ap.get("x_m") if ap.get("x_m") is not None else ap.get("x")
        y = ap.get("y_m") if ap.get("y_m") is not None else ap.get("y")
        if x is None or y is None:
            continue
        aps.append(AccessPoint(
            name=str(ap.get("id") or ap.get("name") or f"ap{i + 1}"),
            x=float(x),
            y=float(y),
            tx_power_dbm=float(ap.get("tx_power_dbm") or ap.get("power_dbm") or 20.0),
        ))
    return aps


def _grid_search_topn(
    *,
    candidates: list[tuple[float, float]],
    eval_points: list[Measurement],
    existing_aps: list[AccessPoint],
    walls: list[WallSegment],
    params: CalibrationParams,
    shadow_threshold_dbm: float,
    shadow_penalty: float,
    n: int,
) -> list[tuple[float, float, float]]:
    """모든 후보 좌표에 대해 점수 계산 후 상위 n개 반환 (x, y, score)."""
    scored: list[tuple[float, float, float]] = []

    for (cx, cy) in candidates:
        test_ap = AccessPoint(name="test", x=cx, y=cy)
        all_aps = existing_aps + [test_ap]

        score = 0.0
        for ep in eval_points:
            pred = predict_rssi_best_ap(all_aps, ep, walls, params)
            if pred < shadow_threshold_dbm:
                score -= shadow_penalty
            else:
                score += pred

        scored.append((cx, cy, score))

    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[:n]
