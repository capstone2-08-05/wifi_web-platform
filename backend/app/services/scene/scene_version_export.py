"""SceneVersion → RF inference 컨테이너용 scene.json 변환.

RF 컨테이너의 `app/runtime.py` 가 기대하는 형식:
  {
    "walls": [{x1, y1, x2, y2, thickness, height, material}],
    "rooms": [{points: [[x,y], ...]}]
  }

좌표 단위는 **미터**. SceneVersion 의 wall/room PostGIS geometry (SRID=0, meter) 를
GeoJSON 으로 변환한 뒤 좌표를 추출한다.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
from app.models import Opening, Room, SceneVersion, Wall
from app.services.rf.scene_obstacles import column_wall_segments_for_objects, normalize_rf_material

logger = logging.getLogger(__name__)

DEFAULT_WALL_THICKNESS_M = 0.12
DEFAULT_WALL_HEIGHT_M = 2.6
DEFAULT_WALL_MATERIAL = "plasterboard"

# Sionna 1.0.2 의 ITURadioMaterial type 인자가 받는 enum (소문자, prefix 없음).
# 출처: ITU-R P.2040 표준. 컨테이너 (`apps/sagemaker_rf_inference`) 가
# scene.json 의 walls[*].material 을 그대로 ITURadioMaterial(name, type, ...)
# 의 type 으로 넘기므로, 이 set 안의 값만 보내야 함.
SIONNA_MATERIAL_SET: set[str] = {
    "vacuum",
    "concrete",
    "brick",
    "plasterboard",
    "wood",
    "glass",
    "ceiling_board",
    "chipboard",
    "floorboard",
    "metal",
    "very_dry_ground",
    "medium_dry_ground",
    "wet_ground",
}
# 우리 material_code → Sionna enum.
MATERIAL_ALIAS: dict[str, str] = {
    "drywall": "plasterboard",
    "marble": "concrete",   # Sionna 1.0.2 에 marble 없음 → 가장 비슷한 concrete 로
    "plywood": "wood",
    "plastic": "chipboard",
    # DB material_name (\ud55c\uad6d\uc5b4) \u2192 Sionna key
    "\uc720\ub9ac": "glass",           # \uc720\ub9ac
    "\ub098\ubb34": "wood",            # \ub098\ubb34 (\uad6c \ud638\ud658)
    "\ubaa9\uc7ac": "wood",            # \ubaa9\uc7ac (DB material_name)
    "\ucf58\ud06c\ub9ac\ud2b8": "concrete",  # \ucf58\ud06c\ub9ac\ud2b8
    "\ubcbd\ub3cc": "brick",           # \ubcbd\ub3cc
    "\uc11d\uace0\ubcf4\ub4dc": "plasterboard",  # \uc11d\uace0\ubcf4\ub4dc
    "\uae08\uc18d": "metal",           # \uae08\uc18d
    "\ud50c\ub77c\uc2a4\ud2f1": "chipboard",  # \ud50c\ub77c\uc2a4\ud2f1
}
SIONNA_FALLBACK = "plasterboard"


def _to_sionna_material(name: str | None) -> str:
    if not name:
        return SIONNA_FALLBACK
    key = name.lower().strip()
    # 옛 ITU prefix 가 묻어있으면 떼어냄
    if key.startswith("itu_"):
        key = key[len("itu_"):]
    key = MATERIAL_ALIAS.get(key, key)
    if key in SIONNA_MATERIAL_SET:
        return key
    return SIONNA_FALLBACK


def export_scene_version_to_scene_json(
    db: Session, scene_version_id: str
) -> dict[str, Any]:
    """SceneVersion 의 walls + rooms 를 RF 컨테이너용 scene.json dict 로 변환.

    빈 SceneVersion (walls 0개 등) 도 통과시킴 — 컨테이너 측에서 적당히 처리.
    """
    sv = (
        db.query(SceneVersion)
        .options(
            selectinload(SceneVersion.walls),
            selectinload(SceneVersion.rooms),
            selectinload(SceneVersion.objects),
            selectinload(SceneVersion.openings),
        )
        .filter(SceneVersion.id == scene_version_id)
        .first()
    )
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            f"SceneVersion {scene_version_id} not found.",
            404,
        )

    walls_out: list[dict[str, Any]] = []
    for w in sv.walls:
        line = _extract_linestring(w.centerline_geom)
        if line is None or len(line) < 2:
            continue
        x1, y1 = line[0]
        x2, y2 = line[-1]
        walls_out.append(
            {
                "id": str(w.id),
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "thickness": float(w.thickness_m or DEFAULT_WALL_THICKNESS_M),
                "height": float(w.height_m or DEFAULT_WALL_HEIGHT_M),
                "material": _to_sionna_material(
                    normalize_rf_material(w.material_label, DEFAULT_WALL_MATERIAL)
                ),
            }
        )

    for seg in column_wall_segments_for_objects(sv.objects):
        walls_out.append(
            {
                "x1": float(seg["x1"]),
                "y1": float(seg["y1"]),
                "x2": float(seg["x2"]),
                "y2": float(seg["y2"]),
                "thickness": float(seg["thickness_m"]),
                "height": DEFAULT_WALL_HEIGHT_M,
                "material": _to_sionna_material(str(seg["material"] or DEFAULT_WALL_MATERIAL)),
            }
        )

    rooms_out: list[dict[str, Any]] = []
    for r in sv.rooms:
        polygon = _extract_polygon_exterior(r.polygon_geom)
        if polygon is None or len(polygon) < 3:
            continue
        rooms_out.append({"points": [[float(p[0]), float(p[1])] for p in polygon]})

    # 문/창문(opening) — sionna_runtime 이 wall split + opening_box 처리에 사용.
    # wall_id 는 위 walls_out 의 "id" 필드와 동일한 UUID 여야 매칭됨.
    DEFAULT_DOOR_MATERIAL = "wood"
    DEFAULT_WINDOW_MATERIAL = "glass"
    openings_out: list[dict[str, Any]] = []
    for op in (sv.openings or []):
        if not op.wall_id:
            continue
        line = _extract_linestring(op.line_geom)
        if line is None or len(line) < 2:
            continue
        # 중심점: LineString 전체 좌표의 평균
        cx = sum(p[0] for p in line) / len(line)
        cy = sum(p[1] for p in line) / len(line)
        # 재질: metadata_json.material 우선, 없으면 opening_type 기반 기본값
        raw_mat = (op.metadata_json or {}).get("material")
        default_mat = DEFAULT_DOOR_MATERIAL if op.opening_type == "door" else DEFAULT_WINDOW_MATERIAL
        sionna_key = _to_sionna_material(raw_mat or default_mat)
        openings_out.append(
            {
                "id": str(op.id),
                "wall_id": str(op.wall_id),
                "center_xy": [float(cx), float(cy)],
                "width_m": float(op.width_m),
                "height_m": float(op.height_m),
                "bottom_z_m": float(op.sill_height_m or 0.0),
                "sionna_material_key": sionna_key,
                "material_id": sionna_key,
            }
        )

    if not walls_out:
        # walls 가 0개면 RF 시뮬은 의미가 없음 (장애물 없는 평지 시뮬).
        # 컨테이너가 죽지 않게는 통과시키되 경고만 남김.
        logger.warning(
            "SceneVersion %s exported to scene.json with 0 walls — RF simulation will be trivial",
            scene_version_id,
        )

    return {"walls": walls_out, "rooms": rooms_out, "openings": openings_out}


def _extract_linestring(geom: Any) -> list[tuple[float, float]] | None:
    """WKBElement (LineString) → [(x, y), ...]."""
    gj = wkb_to_geojson(geom)
    if not gj or gj.get("type") != "LineString":
        return None
    coords = gj.get("coordinates") or []
    return [(c[0], c[1]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]


def _extract_polygon_exterior(geom: Any) -> list[tuple[float, float]] | None:
    """WKBElement (Polygon) → [(x, y), ...] (외곽 ring)."""
    gj = wkb_to_geojson(geom)
    if not gj or gj.get("type") != "Polygon":
        return None
    rings = gj.get("coordinates") or []
    if not rings:
        return None
    exterior = rings[0]
    return [(c[0], c[1]) for c in exterior if isinstance(c, (list, tuple)) and len(c) >= 2]
