"""SceneSchema (픽셀 좌표) → PostGIS geometry (미터 좌표) 변환 헬퍼.

scene_draft_service 의 save_scene_draft 가 사용. 분리 이유:
  - 단위 변환 + WKT 빌드 로직만 따로 테스트 가능
  - 다른 서비스 (예: 향후 RF 시뮬 입력 빌드) 에서도 재사용
"""
from __future__ import annotations

from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point, Polygon

SRID = 0


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def px_to_m(value: float | None, scale_ratio: float) -> float | None:
    if value is None:
        return None
    return float(value) * float(scale_ratio)


def wall_centerline_geom(wall: dict[str, Any], scale_ratio: float):
    """Wall dict {x1, y1, x2, y2} (픽셀) → PostGIS LINESTRING (미터)."""
    x1 = _to_float(wall.get("x1"))
    y1 = _to_float(wall.get("y1"))
    x2 = _to_float(wall.get("x2"))
    y2 = _to_float(wall.get("y2"))
    if None in (x1, y1, x2, y2):
        return None
    line = LineString(
        [
            (x1 * scale_ratio, y1 * scale_ratio),
            (x2 * scale_ratio, y2 * scale_ratio),
        ]
    )
    if line.is_empty:
        return None
    return from_shape(line, srid=SRID)


def opening_line_geom(opening: dict[str, Any], scale_ratio: float):
    """Opening bbox (픽셀) → LINESTRING (미터). bbox 의 긴 축 중심선 사용."""
    x1 = _to_float(opening.get("x1"))
    y1 = _to_float(opening.get("y1"))
    x2 = _to_float(opening.get("x2"))
    y2 = _to_float(opening.get("y2"))
    if None in (x1, y1, x2, y2):
        return None
    bw = abs(x2 - x1)
    bh = abs(y2 - y1)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    if bw >= bh:
        # 수평 bbox → 수평 선분
        pts_px = [(x1, cy), (x2, cy)]
    else:
        pts_px = [(cx, y1), (cx, y2)]
    line = LineString([(p[0] * scale_ratio, p[1] * scale_ratio) for p in pts_px])
    if line.is_empty:
        return None
    return from_shape(line, srid=SRID)


def room_polygon_geom(room: dict[str, Any], scale_ratio: float):
    """Room.points (List[[x,y]] 픽셀) → POLYGON (미터). 닫힌 ring 보장."""
    points_raw = room.get("points") or []
    pts: list[tuple[float, float]] = []
    for p in points_raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        x = _to_float(p[0])
        y = _to_float(p[1])
        if x is None or y is None:
            continue
        pts.append((x * scale_ratio, y * scale_ratio))
    if len(pts) < 3:
        return None
    # ring close
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    polygon = Polygon(pts)
    if polygon.is_empty or not polygon.is_valid:
        return None
    return from_shape(polygon, srid=SRID)


def room_centroid_geom(room: dict[str, Any], scale_ratio: float):
    """Room.center [x, y] (픽셀) → POINT (미터)."""
    center = room.get("center") or []
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    x = _to_float(center[0])
    y = _to_float(center[1])
    if x is None or y is None:
        return None
    point = Point(x * scale_ratio, y * scale_ratio)
    if point.is_empty:
        return None
    return from_shape(point, srid=SRID)


def object_point_geom(obj: dict[str, Any], scale_ratio: float):
    """Object (DetectionDTO dump) bbox_xyxy 의 중심 → POINT (미터)."""
    bbox = obj.get("bbox_xyxy") or []
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    x1 = _to_float(bbox[0])
    y1 = _to_float(bbox[1])
    x2 = _to_float(bbox[2])
    y2 = _to_float(bbox[3])
    if None in (x1, y1, x2, y2):
        return None
    cx = ((x1 + x2) / 2.0) * scale_ratio
    cy = ((y1 + y2) / 2.0) * scale_ratio
    point = Point(cx, cy)
    if point.is_empty:
        return None
    return from_shape(point, srid=SRID)
