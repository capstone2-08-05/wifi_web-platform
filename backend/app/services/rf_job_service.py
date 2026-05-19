"""RF 시뮬레이션 Job (job_type='rf_simulate') 오케스트레이션.

흐름 (ai_api 동기 호출 + background task):
  - submit_rf_simulation: SceneVersion → scene.json + Job/RfRun row 생성 + background task 스폰
  - 백그라운드 태스크가 ai_api Sionna 호출 → values_dbm 받아 matplotlib PNG 렌더링 →
    로컬 저장소 + RfMap row + RfRun/Job done

기존 SageMaker 비동기 패턴 (S3 polling) 은 제거됨. ai_api 가 단일 AP 만 받기 때문에
multi-AP 케이스는 첫 AP 만 시뮬 (현 한계, 추후 N회 호출 + 합성으로 확장).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.db.session import SessionLocal
from app.models import Job, Project, RfRun, SceneVersion, User
from app.models.rf_map import RfMap
from app.services import _local_storage as _storage
from app.services import ai_inference_client
from app.services.ai_inference_client import _SionnaCallInputs
from app.services.sagemaker_rf_inference_service import (
    SageMakerRfInferenceFailure,
    map_rf_failure_to_app_error,
)
from app.services.scene_version_export import export_scene_version_to_scene_json

logger = logging.getLogger(__name__)

JOB_TYPE_RF_SIMULATE = "rf_simulate"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"


# ============================================================
# Submit
# ============================================================
async def submit_rf_simulation(
    db: Session,
    *,
    scene_version_id: UUID,
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    current_user: User,
    run_type: str = "rf_simulate",
    metadata: dict[str, Any] | None = None,
) -> tuple[RfRun, Job]:
    """SceneVersion 확인 + scene.json export + SageMaker submit + Job/RfRun row 생성.

    반환: (rf_run, job) — 둘 다 commit 완료된 상태.
    """
    sv = _get_owned_scene_version(db, scene_version_id, current_user)

    # 1) scene.json 빌드 (DB → dict)
    try:
        scene_json = export_scene_version_to_scene_json(db, sv.id)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            ErrorCode.SCENE_VERSION_EXPORT_FAILED,
            f"Failed to build scene.json from SceneVersion {sv.id}: {exc}",
            500,
        ) from exc

    now = _now_utc()

    # 2) RfRun row
    rf_run = RfRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        run_type=run_type,
        status=JOB_STATUS_RUNNING,
        request_json={
            "access_points": access_points,
            "simulation": simulation,
            "metadata": metadata or {},
        },
        metrics_json={},
    )

    # 3) Job row
    input_json: dict[str, Any] = {
        "rf_run_id": None,
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "requested_by": current_user.email,
        "ai_api": {
            "engine": "sionna_rt",
        },
    }
    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type=JOB_TYPE_RF_SIMULATE,
        status=JOB_STATUS_RUNNING,
        input_json=input_json,
        result_json={},
        started_at=now,
    )

    try:
        db.add(rf_run)
        db.flush()
        input_json["rf_run_id"] = rf_run.id
        job.input_json = input_json
        db.add(job)
        db.commit()
        db.refresh(rf_run)
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to persist RF simulation job: {exc}",
            500,
        ) from exc

    # 4) ai_api 호출은 background task 로
    asyncio.create_task(
        _run_rf_pipeline_in_background(
            job_id=str(job.id),
            rf_run_id=str(rf_run.id),
            scene_json=scene_json,
            access_points=access_points,
            simulation=simulation,
            floor_id=str(sv.floor_id),
        )
    )

    logger.info("RF job submitted job_id=%s rf_run_id=%s", job.id, rf_run.id)
    return rf_run, job


# ============================================================
# Background pipeline (ai_api Sionna 호출 + PNG 렌더링 + RfMap 저장)
# ============================================================
async def _run_rf_pipeline_in_background(
    *,
    job_id: str,
    rf_run_id: str,
    scene_json: dict[str, Any],
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    floor_id: str,
) -> None:
    """ai_api Sionna 호출 → values_dbm 받아 PNG 렌더 + RfMap row 생성 + Job done."""
    db = SessionLocal()
    try:
        try:
            ai_scene = _convert_scene_to_ai_api(scene_json)
            if not access_points:
                raise AppError(
                    ErrorCode.INVALID_REQUEST_BODY,
                    "RF simulation requires at least 1 access point.",
                    400,
                )
            ai_plane = _build_measurement_plane(scene_json, simulation)
            ai_sim = _build_sionna_sim_section(simulation)

            # ai_api 는 단일 AP 만 받음 — AP 마다 한 번씩 호출해서 셀당 max (best AP) 로 합침.
            artifacts, full_response = await _simulate_multi_ap(
                job_id=job_id,
                ai_scene=ai_scene,
                access_points=access_points,
                ai_plane=ai_plane,
                ai_sim=ai_sim,
                floor_id=floor_id,
            )
        except SageMakerRfInferenceFailure as failure:
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed_from_container(db, job, failure)
            return
        except AppError as exc:
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job, code=exc.code, stage="ai_api_call", message=exc.message,
                )
            return
        except Exception as exc:
            logger.exception("ai_api Sionna call failed for job %s", job_id)
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job,
                    code=ErrorCode.INTERNAL_SERVER_ERROR,
                    stage="ai_api_call",
                    message=f"Unexpected ai_api error: {exc}",
                )
            return

        # values_dbm → PNG + RfMap row (scene_json 도 넘겨서 방 폴리곤 마스크 적용)
        try:
            heatmap_uri, radio_map_uri, render_meta = _render_and_save_rf_outputs(
                artifacts, rf_run_id, scene_json=scene_json,
            )
        except Exception as exc:
            logger.exception("RF render failed for job %s", job_id)
            job = db.get(Job, job_id)
            if job is not None:
                _mark_job_failed(
                    db, job,
                    code=ErrorCode.INTERNAL_SERVER_ERROR,
                    stage="render_outputs",
                    message=f"Failed to render RF outputs: {exc}",
                )
            return

        _finalize_rf_job(
            db,
            job_id=job_id,
            rf_run_id=rf_run_id,
            artifacts=artifacts,
            ai_api_metrics=full_response.get("metrics") or {},
            heatmap_uri=heatmap_uri,
            radio_map_uri=radio_map_uri,
            render_meta=render_meta,
        )
    finally:
        db.close()


# ----- 멀티 AP 시뮬 (ai_api 는 단일 AP 만 받아 N번 호출 + max 합성) -----
async def _simulate_multi_ap(
    *,
    job_id: str,
    ai_scene: dict[str, Any],
    access_points: list[dict[str, Any]],
    ai_plane: dict[str, Any],
    ai_sim: dict[str, Any],
    floor_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """AP 마다 ai_api 호출 → 셀당 max RSSI (best AP coverage) 로 합성.

    합성 응답 구조는 단일 AP 응답과 동일하게 맞춰서 _finalize / _render 가 그대로 동작.
    """
    combined_values: np.ndarray | None = None
    combined_valid: np.ndarray | None = None
    bounds: dict[str, Any] | None = None
    first_response: dict[str, Any] | None = None

    for i, ap_dict in enumerate(access_points):
        ai_ap = _convert_ap_to_ai_api(ap_dict)
        inputs = _SionnaCallInputs(
            scene=ai_scene,
            access_point=ai_ap,
            measurement_plane=ai_plane,
            simulation=ai_sim,
            floor_id=floor_id,
            run_type="run",
        )
        rf_result, artifacts = await ai_inference_client.simulate_rf(
            job_id=f"{job_id}-ap{i}", inputs=inputs,
        )
        radiomap = artifacts.get("radiomap") or {}
        values = radiomap.get("values_dbm")
        if not values:
            logger.warning("AP %s response missing radiomap.values_dbm — skipped", ai_ap.get("id"))
            continue
        arr = np.asarray(values, dtype=np.float32)
        valid = np.isfinite(arr) & (arr > -200)

        if combined_values is None:
            combined_values = np.where(valid, arr, -np.inf)
            combined_valid = valid
            bounds = radiomap.get("bounds_m") or {}
            first_response = rf_result.result_payload
        else:
            # 셀당 max RSSI
            ap_arr = np.where(valid, arr, -np.inf)
            combined_values = np.maximum(combined_values, ap_arr)
            combined_valid = combined_valid | valid

    if combined_values is None:
        raise AppError(
            ErrorCode.RF_SIMULATION_FAILED,
            "All AP simulations failed (no valid radiomap returned).",
            502,
        )

    # 합성 결과를 단일 AP 응답 형식으로 패킹
    finite_mask = np.isfinite(combined_values)
    final_values = np.where(finite_mask, combined_values, -300.0)  # -inf → very low dBm

    grid_shape = list(combined_values.shape)
    combined_artifacts: dict[str, Any] = {
        "radiomap": {
            "values_dbm": final_values.tolist(),
            "grid_shape": grid_shape,
            "bounds_m": bounds or {},
        },
        "rssi": {
            "min": float(combined_values[combined_valid].min()) if combined_valid.any() else None,
            "max": float(combined_values[combined_valid].max()) if combined_valid.any() else None,
            "mean": float(combined_values[combined_valid].mean()) if combined_valid.any() else None,
            "valid": {},
        },
        "valid_ratio": float(combined_valid.mean()) if combined_valid.size else 0.0,
    }

    # 평균 RSSI / 커버리지 계산 (프론트가 metrics_json.rss_dbm / coverage_summary 읽음)
    valid_arr = combined_values[combined_valid]
    rssi_mean = float(valid_arr.mean()) if valid_arr.size else None
    rssi_min = float(valid_arr.min()) if valid_arr.size else None
    rssi_max = float(valid_arr.max()) if valid_arr.size else None

    total_cells = combined_valid.size
    valid_cells = int(combined_valid.sum())
    ge_67 = float((valid_arr >= -67).mean()) if valid_arr.size else 0.0
    ge_70 = float((valid_arr >= -70).mean()) if valid_arr.size else 0.0
    ge_75 = float((valid_arr >= -75).mean()) if valid_arr.size else 0.0
    valid_cell_ratio = float(valid_cells / total_cells) if total_cells else 0.0

    combined_metrics: dict[str, Any] = {
        "rssi_summary": {"min": rssi_min, "max": rssi_max, "mean": rssi_mean},
        "coverage_summary": {
            "ge_-67": ge_67,
            "ge_-70": ge_70,
            "ge_-75": ge_75,
            "valid_cell_count": valid_cells,
            "total_cell_count": total_cells,
            "valid_cell_ratio": valid_cell_ratio,
        },
        "valid_ratio": valid_cell_ratio,
        "n_access_points": len(access_points),
    }

    full_response = dict(first_response or {})
    full_response["metrics"] = combined_metrics
    full_response["artifacts"] = combined_artifacts

    return combined_artifacts, full_response


# ----- 변환 헬퍼 (legacy scene.json → ai_api FloorScene) -----
def _convert_scene_to_ai_api(scene_json: dict[str, Any]) -> dict[str, Any]:
    """legacy scene_json {walls: [{x1,y1,x2,y2,...}], rooms: [{points}]} →
    ai_api FloorScene {walls: [{id, start_xy, end_xy, ...}], rooms: [{id, polygon_xy}], ...}.
    """
    walls_out: list[dict[str, Any]] = []
    for i, w in enumerate(scene_json.get("walls") or []):
        walls_out.append({
            "id": f"w{i}",
            "start_xy": [float(w.get("x1", 0.0)), float(w.get("y1", 0.0))],
            "end_xy": [float(w.get("x2", 0.0)), float(w.get("y2", 0.0))],
            "thickness_m": float(w.get("thickness") or 0.12),
            "height_m": float(w.get("height") or 2.6),
            "material_id": str(w.get("material") or "concrete"),
        })

    rooms_out: list[dict[str, Any]] = []
    for i, r in enumerate(scene_json.get("rooms") or []):
        pts = r.get("points") or r.get("polygon_xy") or []
        if len(pts) >= 3:
            rooms_out.append({
                "id": f"r{i}",
                "polygon_xy": [[float(p[0]), float(p[1])] for p in pts],
            })

    return {
        "walls": walls_out,
        "openings": [],
        "rooms": rooms_out,
        "furniture": [],
    }


def _convert_ap_to_ai_api(ap: dict[str, Any]) -> dict[str, Any]:
    """프론트 access_point dict → ai_api AccessPoint.

    프론트는 {id, x_m, y_m, z_m} 보냄. legacy {x, y, z} 도 호환.
    ai_api 는 {id, position_m: [x, y, z], ...} 받음.
    """
    pos = ap.get("position") or ap.get("position_m")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        x, y = float(pos[0]), float(pos[1])
        z = float(pos[2]) if len(pos) >= 3 else float(ap.get("z_m") or ap.get("z") or 2.5)
    else:
        x = float(ap.get("x_m") if ap.get("x_m") is not None else (ap.get("x") or 0.0))
        y = float(ap.get("y_m") if ap.get("y_m") is not None else (ap.get("y") or 0.0))
        z = float(ap.get("z_m") if ap.get("z_m") is not None else (ap.get("z") or 2.5))

    out: dict[str, Any] = {
        "id": str(ap.get("id") or ap.get("name") or "ap1"),
        "position_m": [x, y, z],
        "name": ap.get("name"),
    }
    if ap.get("tx_power_dbm") is not None:
        out["tx_power_dbm"] = float(ap["tx_power_dbm"])
    if ap.get("frequency_ghz") is not None:
        out["frequency_ghz"] = float(ap["frequency_ghz"])
    elif ap.get("frequency_hz") is not None:
        out["frequency_ghz"] = float(ap["frequency_hz"]) / 1e9
    return out


def _build_measurement_plane(
    scene_json: dict[str, Any], simulation: dict[str, Any]
) -> dict[str, Any]:
    """프론트 simulation dict → ai_api MeasurementPlane.

    프론트는 measurement_plane_z_m / resolution_m 으로 보냄.
    ai_api 는 z_m / cell_size_m 받음.
    """
    z_m = float(
        simulation.get("measurement_plane_z_m")
        or simulation.get("measurement_z_m")
        or simulation.get("z_m")
        or 1.0
    )
    cell_size_m = float(
        simulation.get("resolution_m")
        or simulation.get("cell_size_m")
        or 0.25
    )
    return {"z_m": z_m, "cell_size_m": cell_size_m}


def _build_sionna_sim_section(simulation: dict[str, Any]) -> dict[str, Any]:
    """프론트 simulation dict → ai_api simulation {physical, propagation, solver}.

    프론트 flat 키 (frequency_hz, tx_power_dbm, max_depth, samples_per_tx, seed)
    들을 ai_api 의 nested 구조로 매핑한다. 이미 nested 면 그대로 통과.
    """
    out: dict[str, Any] = {}

    # 이미 nested 면 그대로
    if "physical" in simulation or "propagation" in simulation or "solver" in simulation:
        if "physical" in simulation:
            out["physical"] = simulation["physical"]
        if "propagation" in simulation:
            out["propagation"] = simulation["propagation"]
        if "solver" in simulation:
            out["solver"] = simulation["solver"]
        return out

    # flat → nested 변환
    physical: dict[str, Any] = {}
    if simulation.get("frequency_ghz") is not None:
        physical["frequency_ghz"] = float(simulation["frequency_ghz"])
    elif simulation.get("frequency_hz") is not None:
        physical["frequency_ghz"] = float(simulation["frequency_hz"]) / 1e9
    if simulation.get("tx_power_dbm") is not None:
        physical["tx_power_dbm"] = float(simulation["tx_power_dbm"])
    if simulation.get("tx_power_offset_db") is not None:
        physical["tx_power_offset_db"] = float(simulation["tx_power_offset_db"])
    if physical:
        out["physical"] = physical

    solver: dict[str, Any] = {}
    if simulation.get("max_depth") is not None:
        solver["max_depth"] = int(simulation["max_depth"])
    if simulation.get("samples_per_tx") is not None:
        solver["samples_per_tx"] = int(simulation["samples_per_tx"])
    if simulation.get("seed") is not None:
        solver["seed"] = int(simulation["seed"])
    if solver:
        out["solver"] = solver

    return out


# ----- 결과 렌더링 (values_dbm → PNG + npy → 로컬 저장) -----
def _render_and_save_rf_outputs(
    artifacts: dict[str, Any],
    rf_run_id: str,
    scene_json: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """ai_api artifacts.radiomap.values_dbm → heatmap.png + radio_map.npy (로컬 저장).

    scene_json 의 rooms 폴리곤이 있으면 그 영역으로 alpha 마스크 (도면 밖 투명).
    """
    radiomap = artifacts.get("radiomap") or {}
    values = radiomap.get("values_dbm")
    if not values:
        raise AppError(
            ErrorCode.RF_SIMULATION_FAILED,
            "ai_api Sionna response missing artifacts.radiomap.values_dbm",
            502,
        )
    arr = np.asarray(values, dtype=np.float32)
    bounds = radiomap.get("bounds_m") or {}

    # 방 폴리곤 마스크 (도면 안쪽만 칠해지게)
    room_mask = _build_room_mask(scene_json, arr.shape, bounds) if scene_json else None

    # heatmap PNG (matplotlib jet, 자동 vmin/vmax)
    png_bytes = _render_heatmap_png(arr, bounds, room_mask=room_mask)
    npy_buf = io.BytesIO()
    np.save(npy_buf, arr)

    heatmap_key = f"rf-heatmaps/{rf_run_id}/heatmap.png"
    radio_map_key = f"rf-heatmaps/{rf_run_id}/radio_map.npy"

    heatmap_uri = _storage.upload_bytes(heatmap_key, png_bytes, content_type="image/png")
    radio_map_uri = _storage.upload_bytes(
        radio_map_key, npy_buf.getvalue(), content_type="application/octet-stream"
    )

    render_meta = {
        "grid_shape": list(arr.shape),
        "bounds_m": bounds,
        "min_dbm": float(arr.min()) if arr.size > 0 else None,
        "max_dbm": float(arr.max()) if arr.size > 0 else None,
        "mean_dbm": float(arr.mean()) if arr.size > 0 else None,
    }
    return heatmap_uri, radio_map_uri, render_meta


def _build_room_mask(
    scene_json: dict[str, Any] | None,
    shape: tuple[int, int],
    bounds: dict[str, Any],
) -> np.ndarray | None:
    """rooms 폴리곤들을 raster 화해서 (H, W) bool mask 반환. True = 방 안쪽."""
    if not scene_json:
        return None
    rooms = scene_json.get("rooms") or []
    if not rooms or not bounds:
        return None
    from PIL import Image, ImageDraw

    h, w = shape
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", 0.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 0.0))
    if max_x <= min_x or max_y <= min_y:
        return None

    sx = w / (max_x - min_x)
    sy = h / (max_y - min_y)

    img = Image.new("L", (w, h), 0)
    drawer = ImageDraw.Draw(img)
    for r in rooms:
        pts = r.get("points") or r.get("polygon_xy") or []
        if len(pts) < 3:
            continue
        # 미터 → 픽셀. origin=lower 라 y 축 뒤집기 X (matplotlib 이 알아서 처리)
        pixel_pts = [
            ((float(p[0]) - min_x) * sx, (float(p[1]) - min_y) * sy)
            for p in pts
        ]
        drawer.polygon(pixel_pts, fill=255)

    return np.array(img) > 0


def _render_heatmap_png(
    arr: np.ndarray,
    bounds: dict[str, Any],
    room_mask: np.ndarray | None = None,
) -> bytes:
    """matplotlib 으로 RSSI heatmap PNG 생성 (축/제목/컬러바 없는 raw 이미지).

    프론트가 도면 위에 bounds 영역으로 오버레이하므로, PNG 는 색상 그리드만 담아야
    위치/크기가 1:1 로 맞는다. 매우 낮은 RSSI (invalid cell) 는 vmin 으로 clip.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # invalid cell (Sionna 가 ray tracing 못 닿은 영역 — -inf / 매우 낮은 값) 은
    # alpha=0 으로 투명 처리해서 도면 밖이 안 칠해지게 한다.
    valid_mask = np.isfinite(arr) & (arr > -200)
    valid = arr[valid_mask]
    if valid.size > 0:
        vmin = float(np.percentile(valid, 5))
        vmax = float(np.percentile(valid, 95))
        if vmax - vmin < 8.0:
            vmax = vmin + 8.0
    else:
        vmin, vmax = -90.0, -30.0

    # 출력 픽셀 크기를 grid_shape 와 비슷한 비율로
    h, w = arr.shape
    fig = plt.figure(figsize=(w / 50.0, h / 50.0), frameon=False)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_axis_off()

    # 방 폴리곤이 있으면: 방 안쪽은 무조건 칠함. invalid 셀 (Sionna 가 못 닿은 곳) 은
    # vmin 으로 fallback → 진한 파란색 (약한 신호 의미).
    # 방 폴리곤이 없으면: valid_mask 만 사용 (옛 동작).
    if room_mask is not None and room_mask.shape == arr.shape:
        display_arr = np.where(valid_mask, arr, vmin)
        alpha = room_mask.astype(np.float32)
    else:
        display_arr = arr
        alpha = valid_mask.astype(np.float32)

    # origin="upper" — 프론트가 Y-down (위가 작은 y) 으로 표시하므로 PNG 도 같은 방향.
    # PIL room_mask 도 Y-down 이라 자연스럽게 일치.
    ax.imshow(
        display_arr, cmap="jet", origin="upper",
        vmin=vmin, vmax=vmax, interpolation="bilinear", alpha=alpha,
    )
    # 배경 투명 (figure 자체 배경도)
    fig.patch.set_alpha(0.0)
    ax.patch.set_alpha(0.0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, pad_inches=0, bbox_inches=None, transparent=True)
    plt.close(fig)
    return buf.getvalue()


def _finalize_rf_job(
    db: Session,
    *,
    job_id: str,
    rf_run_id: str,
    artifacts: dict[str, Any],
    ai_api_metrics: dict[str, Any],
    heatmap_uri: str,
    radio_map_uri: str,
    render_meta: dict[str, Any],
) -> None:
    """Job + RfRun done 마킹 + RfMap row 2개 생성. race-safe.

    metrics_json 구조는 프론트 SimulationPage.parseMetrics 가 읽는 형식 사용:
      - rss_dbm: {min, max, mean}            ← 평균 RSSI 표시
      - coverage_summary: {ge_-67, valid_cell_ratio, ...}  ← 면적 커버리지 계산
    """
    locked = _lock_job(db, job_id)
    if locked.status != JOB_STATUS_RUNNING:
        return

    # ai_api metrics → 프론트 호환 키로 매핑
    rss_summary = (
        ai_api_metrics.get("rssi_summary")
        or (artifacts.get("rssi") or {}).get("valid")
        or {}
    )
    rss_dbm = {
        "min": rss_summary.get("min"),
        "max": rss_summary.get("max"),
        "mean": rss_summary.get("mean"),
    }
    coverage_summary = (
        ai_api_metrics.get("coverage_summary")
        or artifacts.get("coverage_summary_valid_only")
        or artifacts.get("coverage")
        or {}
    )
    bounds = render_meta["bounds_m"] or {}
    grid_shape = render_meta["grid_shape"]
    valid_ratio = ai_api_metrics.get("valid_ratio") or artifacts.get("valid_ratio")

    metrics_payload: dict[str, Any] = {
        "rss_dbm": rss_dbm,
        "coverage_summary": coverage_summary,
        "valid_ratio": valid_ratio,
        "grid_shape": grid_shape,
        "bounds_m": bounds,
        "ai_api_metrics": ai_api_metrics,  # 디버그용 원본
    }

    rf_run = db.get(RfRun, rf_run_id)
    if rf_run is not None:
        rf_run.status = JOB_STATUS_DONE
        rf_run.metrics_json = metrics_payload

        cell_size_m = 0.25
        if bounds and len(grid_shape) == 2 and grid_shape[1] > 0:
            cell_size_m = (
                float(bounds.get("max_x", 0)) - float(bounds.get("min_x", 0))
            ) / float(grid_shape[1])
        resolution_cm = max(1, int(round(cell_size_m * 100)))

        db.add(RfMap(
            rf_run_id=rf_run.id, map_type="heatmap",
            resolution_cm=resolution_cm, storage_url=heatmap_uri,
            bounds_json=bounds, metrics_json=metrics_payload,
        ))
        db.add(RfMap(
            rf_run_id=rf_run.id, map_type="radio_map_dbm",
            resolution_cm=resolution_cm, storage_url=radio_map_uri,
            bounds_json=bounds, metrics_json=metrics_payload,
        ))

    locked.status = JOB_STATUS_DONE
    locked.result_json = {
        "rf_run_id": rf_run_id,
        "heatmap_url": _storage.static_url(heatmap_uri),
        "radio_map_url": _storage.static_url(radio_map_uri),
        "grid_shape": render_meta["grid_shape"],
    }
    locked.error_message = None
    locked.finished_at = _now_utc()
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark RF job done: {exc}",
            500,
        ) from exc
    logger.info("RF job done job_id=%s rf_run_id=%s", job_id, rf_run_id)


# ============================================================
# Poll & complete
# ============================================================
async def retry_rf_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> tuple[RfRun, Job]:
    """실패한 RF Job 을 동일 input 으로 재제출 → 새 Job/RfRun 생성.

    원본 Job 은 그대로 두고 새 row 를 만든다. 입력 (scene_version_id, access_points,
    simulation, metadata) 은 원본 Job.input_json 에서 그대로 가져옴.

    failed 상태가 아닌 Job 을 retry 하면 409 (충돌). 단, retryable=true 가 아닌
    실패도 사용자가 명시적으로 재시도하면 허용 (운영 판단).
    """
    job = _get_owned_rf_job_or_404(db, job_id, current_user)
    if job.status != JOB_STATUS_FAILED:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"Cannot retry job in status '{job.status}'. Only failed jobs can be retried.",
            status_code=409,
        )

    input_meta = job.input_json or {}
    scene_version_id = input_meta.get("scene_version_id")
    access_points = input_meta.get("access_points")
    simulation = input_meta.get("simulation")
    if not scene_version_id or not access_points or not simulation:
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            "Cannot retry: original Job.input_json missing scene_version_id / access_points / simulation.",
            500,
        )

    metadata = input_meta.get("metadata") or {}
    metadata["retry_of_job_id"] = str(job.id)

    return await submit_rf_simulation(
        db,
        scene_version_id=UUID(str(scene_version_id)),
        access_points=access_points,
        simulation=simulation,
        current_user=current_user,
        metadata=metadata,
    )


async def poll_rf_job(
    db: Session,
    *,
    job_id: str,
    current_user: User,
) -> Job:
    """RF Job 조회만. ai_api 흐름에서는 background task 가 마무리한다."""
    return _get_owned_rf_job_or_404(db, job_id, current_user)


def _mark_job_failed_from_container(
    db: Session, job: Job, failure: SageMakerRfInferenceFailure
) -> Job:
    app_error = map_rf_failure_to_app_error(failure)
    return _mark_job_failed(
        db, job,
        code=app_error.code,
        stage=failure.stage,
        message=failure.message,
        container_code=failure.code,
        details=failure.details,
    )


def _mark_job_failed(
    db: Session,
    job: Job,
    *,
    code: ErrorCode,
    stage: str,
    message: str,
    container_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> Job:
    job.status = JOB_STATUS_FAILED
    job.error_message = f"[{stage}] {message}"
    job.result_json = {
        "error": {
            "backend_code": str(code),
            "container_code": container_code,
            "stage": stage,
            "message": message,
            "retryable": (details or {}).get("retryable", False),
            "details": details or {},
        },
    }
    job.finished_at = _now_utc()

    rf_run = _find_associated_rf_run(db, job)
    if rf_run is not None:
        rf_run.status = JOB_STATUS_FAILED

    try:
        db.commit()
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to mark RF job failed: {exc}",
            500,
        ) from exc

    logger.warning(
        "RF job failed job_id=%s code=%s stage=%s message=%s",
        job.id, code, stage, message,
    )
    return job


# ============================================================
# Helpers
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_owned_scene_version(
    db: Session, scene_version_id: UUID, user: User
) -> SceneVersion:
    stmt = (
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(scene_version_id),
            Project.owner_user_id == user.id,
        )
    )
    sv = db.execute(stmt).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            404,
        )
    return sv


def _get_owned_rf_job_or_404(
    db: Session, job_id: str, current_user: User
) -> Job:
    stmt = (
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(
            Job.id == str(job_id),
            Job.job_type == JOB_TYPE_RF_SIMULATE,
            Project.owner_user_id == current_user.id,
        )
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise AppError(ErrorCode.JOB_NOT_FOUND, "RF simulation job not found.", 404)
    return job


def _lock_job(db: Session, job_id: str) -> Job:
    stmt = select(Job).where(Job.id == job_id).with_for_update()
    return db.execute(stmt).scalar_one()


def _claim_and_finalize(db: Session, job_id: str, current_user: User, *, finalize) -> Job:
    locked = _lock_job(db, job_id)
    if locked.status != JOB_STATUS_RUNNING:
        return locked
    return finalize(locked)


def _find_associated_rf_run(db: Session, job: Job) -> RfRun | None:
    """Job.input_json.rf_run_id 로 RfRun 1건 찾음."""
    rf_run_id = (job.input_json or {}).get("rf_run_id")
    if not rf_run_id:
        return None
    return db.execute(
        select(RfRun).where(RfRun.id == str(rf_run_id))
    ).scalar_one_or_none()


# DEPRECATED (AWS 회귀 시 복원): RfMap row 자동 생성은 이제 _finalize_rf_job 가 직접 수행.
# 옛 SageMaker 흐름의 (s3:// URI 기반) 생성기로, 함수 자체는 보존만 한다.
def _create_rf_map_rows(db: Session, rf_run: RfRun, inference) -> None:
    raise NotImplementedError(
        "Legacy SageMaker RfMap creation disabled. See _finalize_rf_job instead."
    )
