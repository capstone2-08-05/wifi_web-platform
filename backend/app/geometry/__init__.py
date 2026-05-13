"""순수(함수형) 공간 helper 모음.

서비스(서비스 클래스 — `app/services/...`) 와 달리 stateless. SceneDraft 영속화 및
도면-인식 결과의 후처리에 쓰인다.

Submodules:
  - conversion: 픽셀 → 미터 + PostGIS geometry 빌더
  - matching:   Opening ↔ Wall 매칭 (거리 + 방향)

Public API 는 여기서 re-export.
"""
from app.geometry.conversion import (
    object_point_geom,
    opening_line_geom,
    px_to_m,
    room_centroid_geom,
    room_polygon_geom,
    wall_centerline_geom,
)
from app.geometry.matching import (
    assign_wall_refs,
    bbox_orientation,
    find_nearest_wall_id,
    opening_bbox_center,
    opening_search_radius_px,
    point_to_segment_distance,
    segment_orientation,
)

__all__ = [
    # conversion
    "object_point_geom",
    "opening_line_geom",
    "px_to_m",
    "room_centroid_geom",
    "room_polygon_geom",
    "wall_centerline_geom",
    # matching
    "assign_wall_refs",
    "bbox_orientation",
    "find_nearest_wall_id",
    "opening_bbox_center",
    "opening_search_radius_px",
    "point_to_segment_distance",
    "segment_orientation",
]
