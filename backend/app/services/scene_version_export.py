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

logger = logging.getLogger(__name__)

DEFAULT_WALL_THICKNESS_M = 0.12
DEFAULT_WALL_HEIGHT_M = 2.6
DEFAULT_WALL_MATERIAL = "plasterboard"


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
                "material": w.material_label or DEFAULT_WALL_MATERIAL,
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
