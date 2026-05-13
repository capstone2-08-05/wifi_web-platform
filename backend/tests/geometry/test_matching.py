"""Opening ↔ Wall 매칭 단위 테스트 (픽셀 좌표계).

Phase 2 — 거리 기반 매칭
Phase 2.5 — 방향(orientation) 일치 1차 필터
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.geometry import (
    assign_wall_refs,
    bbox_orientation,
    find_nearest_wall_id,
    opening_bbox_center,
    opening_search_radius_px,
    point_to_segment_distance,
    segment_orientation,
)


# ============================================================
# 테스트용 stub (Wall / Opening 인터페이스만 충족)
# ============================================================
@dataclass
class _StubWall:
    id: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class _StubOpening:
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    wall_ref: str | None = None


# ============================================================
# point_to_segment_distance
# ============================================================
def test_distance_point_on_segment_is_zero():
    d = point_to_segment_distance(50, 0, 0, 0, 100, 0)
    assert d == pytest.approx(0.0)


def test_distance_perpendicular_from_segment_middle():
    d = point_to_segment_distance(50, 30, 0, 0, 100, 0)
    assert d == pytest.approx(30.0)


def test_distance_beyond_endpoint_clamps_to_endpoint():
    d = point_to_segment_distance(150, 0, 0, 0, 100, 0)
    assert d == pytest.approx(50.0)


def test_distance_degenerate_segment():
    d = point_to_segment_distance(3, 4, 0, 0, 0, 0)
    assert d == pytest.approx(5.0)


# ============================================================
# bbox helpers
# ============================================================
def test_bbox_center():
    cx, cy = opening_bbox_center(100, 200, 300, 400)
    assert (cx, cy) == (200.0, 300.0)


def test_search_radius_uses_long_axis():
    r = opening_search_radius_px(0, 0, 200, 40, tolerance_px=15.0)
    assert r == pytest.approx(115.0)


# ============================================================
# Phase 2.5: 방향 분류
# ============================================================
def test_segment_orientation_horizontal():
    # 길이 100x0 → 수평
    assert segment_orientation(0, 0, 100, 0) == "horizontal"
    # 길이 100x5 → 수평 (dy 가 dx/3 이하)
    assert segment_orientation(0, 0, 100, 5) == "horizontal"


def test_segment_orientation_vertical():
    assert segment_orientation(0, 0, 0, 100) == "vertical"
    assert segment_orientation(0, 0, 5, 100) == "vertical"


def test_segment_orientation_diagonal():
    # 50x50 → 어느 쪽도 우세하지 않음
    assert segment_orientation(0, 0, 50, 50) == "diagonal"


def test_segment_orientation_degenerate():
    assert segment_orientation(0, 0, 0, 0) == "degenerate"


def test_bbox_orientation_horizontal():
    # 100x40 = 가로 길쭉
    assert bbox_orientation(0, 0, 100, 40) == "horizontal"


def test_bbox_orientation_vertical():
    assert bbox_orientation(0, 0, 40, 100) == "vertical"


def test_bbox_orientation_ambiguous_when_near_square():
    # 50x50 → ambiguous
    assert bbox_orientation(0, 0, 50, 50) == "ambiguous"
    # 100x90 → 차이 < 30% → ambiguous
    assert bbox_orientation(0, 0, 100, 90) == "ambiguous"


# ============================================================
# find_nearest_wall_id (Phase 2)
# ============================================================
def _three_walls():
    """┌──── (top)
       │
       │     (left)
       │
       └──── (bottom)"""
    return [
        _StubWall("top", 0, 0, 1000, 0),
        _StubWall("left", 0, 0, 0, 800),
        _StubWall("bottom", 0, 800, 1000, 800),
    ]


def test_door_on_top_wall_matches_top():
    matched = find_nearest_wall_id(450, 5, 550, 45, _three_walls(), max_distance_px=100)
    assert matched == "top"


def test_door_on_bottom_wall_matches_bottom():
    matched = find_nearest_wall_id(450, 770, 550, 810, _three_walls(), max_distance_px=100)
    assert matched == "bottom"


def test_door_on_left_wall_matches_left():
    # 세로 bbox (긴 축이 y) → 세로 wall (left) 매칭
    matched = find_nearest_wall_id(0, 400, 30, 500, _three_walls(), max_distance_px=100)
    assert matched == "left"


def test_floating_opening_beyond_threshold_returns_none():
    matched = find_nearest_wall_id(500, 400, 520, 420, _three_walls(), max_distance_px=50)
    assert matched is None


def test_no_walls_returns_none():
    matched = find_nearest_wall_id(100, 100, 200, 200, [], max_distance_px=100)
    assert matched is None


# ============================================================
# Phase 2.5: 방향 일치 필터
# ============================================================
def test_orientation_filter_picks_horizontal_wall_over_closer_vertical():
    """수평 도어(bbox) — 가까운 수직 벽이 있어도 더 먼 수평 벽을 골라야 함."""
    walls = [
        _StubWall("h", 0, 100, 1000, 100),   # 수평. 도어 (cx=500, cy=20) 에서 80px
        _StubWall("v", 480, 0, 480, 1000),   # 수직. 도어 중심에서 20px (더 가까움)
    ]
    # 도어 bbox: 가로 100, 세로 40 → 수평
    matched = find_nearest_wall_id(
        450, 0, 550, 40, walls, max_distance_px=200, enforce_orientation=True
    )
    assert matched == "h"


def test_orientation_filter_off_picks_nearest_regardless():
    """enforce_orientation=False 면 거리만 본다 (이전 Phase 2 동작)."""
    walls = [
        _StubWall("h", 0, 100, 1000, 100),
        _StubWall("v", 480, 0, 480, 1000),
    ]
    matched = find_nearest_wall_id(
        450, 0, 550, 40, walls, max_distance_px=200, enforce_orientation=False
    )
    # 수직 벽이 더 가까우므로 그쪽 선택
    assert matched == "v"


def test_orientation_fallback_to_any_when_no_match():
    """방향 일치 wall 이 0개면 전체 후보로 fallback (옵션 활성화 시)."""
    walls = [
        _StubWall("v1", 480, 0, 480, 1000),  # 둘 다 수직
        _StubWall("v2", 520, 0, 520, 1000),
    ]
    # 수평 bbox 인데 수평 wall 없음 → fallback 으로 가장 가까운 v1/v2 매칭
    matched = find_nearest_wall_id(
        450, 0, 550, 40, walls, max_distance_px=100,
        enforce_orientation=True, orientation_fallback=True,
    )
    assert matched in {"v1", "v2"}


def test_orientation_no_fallback_returns_none_when_no_orient_match():
    """fallback=False 면 방향 일치 없을 때 None."""
    walls = [
        _StubWall("v1", 480, 0, 480, 1000),
    ]
    matched = find_nearest_wall_id(
        450, 0, 550, 40, walls, max_distance_px=200,
        enforce_orientation=True, orientation_fallback=False,
    )
    assert matched is None


def test_ambiguous_bbox_falls_through_orientation_filter():
    """정사각형에 가까운 bbox 는 방향 필터 skip → 가장 가까운 wall 매칭."""
    walls = [
        _StubWall("h", 0, 100, 1000, 100),    # 80px
        _StubWall("v", 480, 0, 480, 1000),    # 20px (더 가까움)
    ]
    # 50x50 정사각형 도어 (ambiguous orientation)
    matched = find_nearest_wall_id(
        475, 0, 525, 50, walls, max_distance_px=200, enforce_orientation=True
    )
    # 방향 필터 skip → 거리만 → v
    assert matched == "v"


# ============================================================
# assign_wall_refs (in-place mutation)
# ============================================================
def test_assign_wall_refs_sets_wall_ref_and_returns_count():
    walls = _three_walls()
    openings = [
        _StubOpening("o1", 450, 5, 550, 45),        # top (수평 bbox → top)
        _StubOpening("o2", 0, 400, 30, 500),        # left (수직 bbox → left)
        _StubOpening("o3", 9999, 9999, 9999, 9999),  # floating
    ]
    matched = assign_wall_refs(openings, walls, tolerance_px=15.0)
    assert matched == 2
    assert openings[0].wall_ref == "top"
    assert openings[1].wall_ref == "left"
    assert openings[2].wall_ref is None


def test_assign_wall_refs_empty_inputs():
    assert assign_wall_refs([], _three_walls()) == 0
    o = [_StubOpening("o1", 0, 0, 10, 10)]
    assert assign_wall_refs(o, []) == 0
    assert o[0].wall_ref is None
