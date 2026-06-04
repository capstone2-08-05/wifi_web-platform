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
from app.models import Room, SceneVersion, Wall
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
    "\uc720\ub9ac": "glass",
    "\ub098\ubb34": "wood",
    "\ucf58\ud06c\ub9ac\ud2b8": "concrete",
    "\ud50c\ub77c\uc2a4\ud2f1": "chipboard",
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

    if not walls_out:
        # walls 가 0개면 RF 시뮬은 의미가 없음 (장애물 없는 평지 시뮬).
        # 컨테이너가 죽지 않게는 통과시키되 경고만 남김.
        logger.warning(
            "SceneVersion %s exported to scene.json with 0 walls — RF simulation will be trivial",
            scene_version_id,
        )

    return {"walls": walls_out, "rooms": rooms_out}


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
