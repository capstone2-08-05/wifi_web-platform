"""확정본 구성 요소 patch_log 자동 기록 헬퍼"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.geom import wkb_to_geojson
from app.models.object import SceneObject
from app.models.opening import Opening
from app.models.patch_log import PatchLog
from app.models.room import Room
from app.models.user import User
from app.models.wall import Wall


def _decimal_to_str(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    return v


def snapshot_room(r: Room) -> dict[str, Any]:
    return {
        "id": r.id,
        "scene_version_id": r.scene_version_id,
        "room_name": r.room_name,
        "room_type": r.room_type,
        "confidence": _decimal_to_str(r.confidence),
        "source_method": r.source_method,
        "polygon_geom": wkb_to_geojson(r.polygon_geom),
        "centroid_geom": wkb_to_geojson(r.centroid_geom),
        "metadata_json": r.metadata_json or {},
    }


def snapshot_wall(w: Wall) -> dict[str, Any]:
    return {
        "id": w.id,
        "scene_version_id": w.scene_version_id,
        "wall_role": w.wall_role,
        "thickness_m": _decimal_to_str(w.thickness_m),
        "height_m": _decimal_to_str(w.height_m),
        "material_label": w.material_label,
        "confidence": _decimal_to_str(w.confidence),
        "source_method": w.source_method,
        "centerline_geom": wkb_to_geojson(w.centerline_geom),
        "polygon_geom": wkb_to_geojson(w.polygon_geom),
        "metadata_json": w.metadata_json or {},
    }


def snapshot_opening(o: Opening) -> dict[str, Any]:
    return {
        "id": o.id,
        "scene_version_id": o.scene_version_id,
        "wall_id": o.wall_id,
        "opening_type": o.opening_type,
        "width_m": _decimal_to_str(o.width_m),
        "height_m": _decimal_to_str(o.height_m),
        "sill_height_m": _decimal_to_str(o.sill_height_m),
        "confidence": _decimal_to_str(o.confidence),
        "source_method": o.source_method,
        "line_geom": wkb_to_geojson(o.line_geom),
        "polygon_geom": wkb_to_geojson(o.polygon_geom),
        "metadata_json": o.metadata_json or {},
    }


def snapshot_object(o: SceneObject) -> dict[str, Any]:
    return {
        "id": o.id,
        "scene_version_id": o.scene_version_id,
        "object_type": o.object_type,
        "confidence": _decimal_to_str(o.confidence),
        "source_method": o.source_method,
        "point_geom": wkb_to_geojson(o.point_geom),
        "z_m": _decimal_to_str(o.z_m),
        "metadata_json": o.metadata_json or {},
    }


def record_patch(
    db: Session,
    *,
    scene_version_id: str,
    user: User,
    patch_type: str,
    target_type: str,
    target_id: str,
    before: Optional[dict[str, Any]],
    after: Optional[dict[str, Any]],
) -> None:
    """patch_logs 에 INSERT. commit 은 호출자가 책임."""
    log = PatchLog(
        scene_version_id=scene_version_id,
        created_by=user.id,
        patch_type=patch_type,
        target_type=target_type,
        target_id=target_id,
        patch_json={"before": before, "after": after},
    )
    db.add(log)
