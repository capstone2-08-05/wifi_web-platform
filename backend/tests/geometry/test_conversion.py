"""픽셀→미터 변환 + PostGIS geometry 생성 단위 테스트.

DB 없이도 shapely + geoalchemy2.shape.from_shape 동작 검증.
WKT 비교로 변환이 정확한지 확인.
"""
from __future__ import annotations

import pytest
from geoalchemy2.shape import to_shape

from app.geometry import (
    object_point_geom,
    opening_line_geom,
    px_to_m,
    room_centroid_geom,
    room_polygon_geom,
    wall_centerline_geom,
)


SCALE = 0.01  # 1 px = 1 cm = 0.01 m


# ============================================================
# 기본 단위 변환
# ============================================================
def test_px_to_m_basic():
    assert px_to_m(100.0, 0.01) == pytest.approx(1.0)
    assert px_to_m(0.0, 0.01) == pytest.approx(0.0)
    assert px_to_m(None, 0.01) is None


# ============================================================
# Wall centerline
# ============================================================
def test_wall_centerline_geom_normal():
    wall = {"x1": 100, "y1": 200, "x2": 500, "y2": 200}
    geom = wall_centerline_geom(wall, SCALE)
    assert geom is not None
    shape = to_shape(geom)
    coords = list(shape.coords)
    assert coords == [(1.0, 2.0), (5.0, 2.0)]


def test_wall_centerline_geom_missing_coords_returns_none():
    assert wall_centerline_geom({"x1": 1}, SCALE) is None
    assert wall_centerline_geom({}, SCALE) is None


# ============================================================
# Opening line (bbox → 중심선)
# ============================================================
def test_opening_line_geom_horizontal_bbox():
    # 가로 폭 100px, 세로 20px → 수평 중심선
    opening = {"x1": 100, "y1": 90, "x2": 200, "y2": 110}
    geom = opening_line_geom(opening, SCALE)
    assert geom is not None
    coords = list(to_shape(geom).coords)
    # 중심 y = 1.0m, x 범위 1.0 ~ 2.0m
    assert coords == [(1.0, 1.0), (2.0, 1.0)]


def test_opening_line_geom_vertical_bbox():
    # 가로 20px, 세로 100px → 수직 중심선
    opening = {"x1": 90, "y1": 100, "x2": 110, "y2": 200}
    geom = opening_line_geom(opening, SCALE)
    assert geom is not None
    coords = list(to_shape(geom).coords)
    # 중심 x = 1.0m, y 범위 1.0 ~ 2.0m
    assert coords == [(1.0, 1.0), (1.0, 2.0)]


# ============================================================
# Room polygon
# ============================================================
def test_room_polygon_geom_closes_ring():
    room = {
        "points": [[0, 0], [100, 0], [100, 100], [0, 100]],  # 닫혀있지 않음
        "center": [50, 50],
        "area": 1.0,
    }
    geom = room_polygon_geom(room, SCALE)
    assert geom is not None
    shape = to_shape(geom)
    coords = list(shape.exterior.coords)
    # 닫혀야 함: 첫 == 마지막
    assert coords[0] == coords[-1]
    # 각 변 1m × 1m
    assert shape.area == pytest.approx(1.0)


def test_room_polygon_too_few_points():
    room = {"points": [[0, 0], [10, 10]]}
    assert room_polygon_geom(room, SCALE) is None


def test_room_centroid_geom():
    room = {"center": [50, 80]}
    geom = room_centroid_geom(room, SCALE)
    assert geom is not None
    point = to_shape(geom)
    assert (point.x, point.y) == (0.5, 0.8)


# ============================================================
# Object (furniture) point
# ============================================================
def test_object_point_geom_uses_bbox_center():
    obj = {"bbox_xyxy": [100, 200, 300, 400]}
    geom = object_point_geom(obj, SCALE)
    assert geom is not None
    point = to_shape(geom)
    assert (point.x, point.y) == (2.0, 3.0)


def test_object_point_geom_bad_bbox():
    assert object_point_geom({}, SCALE) is None
    assert object_point_geom({"bbox_xyxy": [1, 2]}, SCALE) is None
