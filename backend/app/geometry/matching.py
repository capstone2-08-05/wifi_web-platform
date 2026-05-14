"""Opening (door/window bbox) ↔ 가장 가까운 Wall 매칭.

목적: SceneDraft 저장 시 DraftOpening.wall_id (FK) 를 채우기 위해
      각 opening 의 bbox 중심에서 가장 가까운 wall 선분의 id 를 찾는다.

알고리즘:
  1. opening bbox 의 중심점을 점 P 로 잡음
  2. **방향 일치 후보만 1차 필터** (Phase 2.5): 가로 도어는 가로 벽, 세로 도어는 세로 벽
     - 모양이 애매한 (정사각형에 가까운) bbox 는 방향 필터 skip
     - 방향 일치 후보가 0개면 전체 wall 로 fallback
  3. 후보 중 P 와의 perpendicular 거리가 최소인 wall 선택
  4. 거리가 search_radius 보다 크면 매칭 실패 (이 opening 은 floating)

좌표 단위: 픽셀. 미터 변환은 호출자가 후처리.
"""
from __future__ import annotations

from typing import Iterable, Literal, Protocol

# 방향 분류 임계값 (기본값)
# - segment: 한 축이 다른 축의 N배 이상이면 그 방향. 벽은 보통 hv 정렬돼있어서 3.0 충분.
# - bbox:    bbox 가 N배 이상 길쭉하면 방향 결정. 1.3 = 30% 이상 차이.
DEFAULT_SEGMENT_AXIS_DOMINANCE = 3.0
DEFAULT_BBOX_ASPECT_THRESHOLD = 1.3

# Opening 중복 제거 (NMS) IoU 임계값. 같은 문/창을 두 번 탐지한 경우 제거.
DEFAULT_OPENING_NMS_IOU = 0.5

Bbox = tuple[float, float, float, float]  # (x1, y1, x2, y2)

Orientation = Literal["horizontal", "vertical", "diagonal", "ambiguous", "degenerate"]


class _HasSegment(Protocol):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float


# ============================================================
# 거리
# ============================================================
def point_to_segment_distance(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    """점 P=(px,py) 에서 선분 AB 까지의 최단 거리."""
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        # AB 가 점 (degenerate). 점-점 거리.
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    # AB 위로의 정규화된 projection 계수
    t = ((px - ax) * dx + (py - ay) * dy) / length_squared
    t = max(0.0, min(1.0, t))  # 선분 밖이면 끝점에 clamp
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5


# ============================================================
# bbox 헬퍼
# ============================================================
def opening_bbox_center(
    x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float]:
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def opening_search_radius_px(
    bbox_x1: float,
    bbox_y1: float,
    bbox_x2: float,
    bbox_y2: float,
    tolerance_px: float = 15.0,
) -> float:
    """이 opening 매칭 시 허용할 최대 거리.

    bbox 의 절반 차원 (긴 쪽) + 여유분 — opening 이 벽보다 살짝 어긋나서 그려졌어도 매칭되도록.
    """
    half_w = abs(bbox_x2 - bbox_x1) / 2.0
    half_h = abs(bbox_y2 - bbox_y1) / 2.0
    return max(half_w, half_h) + tolerance_px


# ============================================================
# 방향 분류 (Phase 2.5)
# ============================================================
def segment_orientation(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    axis_dominance: float = DEFAULT_SEGMENT_AXIS_DOMINANCE,
) -> Orientation:
    """선분의 방향을 'horizontal' / 'vertical' / 'diagonal' / 'degenerate' 로 분류."""
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dx == 0.0 and dy == 0.0:
        return "degenerate"
    if dx >= dy * axis_dominance:
        return "horizontal"
    if dy >= dx * axis_dominance:
        return "vertical"
    return "diagonal"


def bbox_orientation(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    aspect_threshold: float = DEFAULT_BBOX_ASPECT_THRESHOLD,
) -> Orientation:
    """bbox 의 긴 축 방향을 'horizontal' / 'vertical' / 'ambiguous' / 'degenerate' 로.

    YOLO 도어 bbox 가 swing arc 때문에 거의 정사각형일 수 있어, 임계값 이내면 'ambiguous'.
    """
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    if w == 0.0 and h == 0.0:
        return "degenerate"
    if w >= h * aspect_threshold:
        return "horizontal"
    if h >= w * aspect_threshold:
        return "vertical"
    return "ambiguous"


def _orientations_compatible(opening_orient: Orientation, wall_orient: Orientation) -> bool:
    """opening 의 긴 축 방향이 wall 방향과 부합하는지.

    Wall 이 diagonal/degenerate 라면 어떤 opening 과도 매칭 가능 (강제 안 함).
    Opening 이 ambiguous/degenerate 라면 호출 측에서 미리 분기.
    """
    if wall_orient in ("diagonal", "degenerate"):
        return True
    return opening_orient == wall_orient


# ============================================================
# Matching
# ============================================================
def find_nearest_wall_id(
    opening_x1: float,
    opening_y1: float,
    opening_x2: float,
    opening_y2: float,
    walls: Iterable[_HasSegment],
    max_distance_px: float,
    enforce_orientation: bool = True,
    orientation_fallback: bool = True,
) -> str | None:
    """opening bbox 중심에서 가장 가까운 wall 의 id 반환.

    Phase 2.5:
      - `enforce_orientation=True` 이고 opening 방향이 명확하면 같은 방향 wall 만 1차 후보.
      - `orientation_fallback=True` 이면 같은 방향 후보가 0개일 때 전체 wall 로 fallback.
        False 면 그냥 None 반환.

    `max_distance_px` 보다 멀면 None (이 opening 은 어떤 wall 에도 부착되지 않음).
    """
    cx, cy = opening_bbox_center(opening_x1, opening_y1, opening_x2, opening_y2)
    walls_list = list(walls)

    opening_orient = bbox_orientation(opening_x1, opening_y1, opening_x2, opening_y2)

    # 방향 1차 필터
    candidates = walls_list
    if enforce_orientation and opening_orient in ("horizontal", "vertical"):
        oriented = [
            w
            for w in walls_list
            if _orientations_compatible(
                opening_orient,
                segment_orientation(w.x1, w.y1, w.x2, w.y2),
            )
        ]
        if oriented:
            candidates = oriented
        elif not orientation_fallback:
            return None

    best_id: str | None = None
    best_dist = float("inf")
    for wall in candidates:
        d = point_to_segment_distance(cx, cy, wall.x1, wall.y1, wall.x2, wall.y2)
        if d < best_dist:
            best_dist = d
            best_id = str(wall.id)

    if best_id is None or best_dist > max_distance_px:
        return None
    return best_id


def assign_wall_refs(
    openings,
    walls,
    tolerance_px: float = 15.0,
    enforce_orientation: bool = True,
) -> int:
    """주어진 openings 의 wall_ref 를 in-place 로 채운다.

    Returns: 매칭에 성공한 opening 수.
    """
    matched = 0
    for opening in openings:
        radius = opening_search_radius_px(
            opening.x1, opening.y1, opening.x2, opening.y2, tolerance_px
        )
        matched_id = find_nearest_wall_id(
            opening.x1,
            opening.y1,
            opening.x2,
            opening.y2,
            walls,
            radius,
            enforce_orientation=enforce_orientation,
        )
        if matched_id is not None:
            opening.wall_ref = matched_id
            matched += 1
    return matched


# ============================================================
# Opening NMS (중복 탐지 제거)
# ============================================================
def bbox_iou(a: Bbox, b: Bbox) -> float:
    """두 bbox 의 IoU (Intersection over Union). 좌표 순서 무관 (자동 정규화)."""
    ax1, ax2 = sorted((a[0], a[2]))
    ay1, ay2 = sorted((a[1], a[3]))
    bx1, bx2 = sorted((b[0], b[2]))
    by1, by2 = sorted((b[1], b[3]))

    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    if inter <= 0.0:
        return 0.0

    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def nms_filter_indices(
    boxes: list[Bbox],
    scores: list[float],
    iou_threshold: float = DEFAULT_OPENING_NMS_IOU,
) -> list[int]:
    """표준 NMS. 겹치는 bbox 중 score 높은 것만 남긴 index 리스트를 **원래 순서**로 반환.

    boxes 와 scores 는 같은 길이. score 가 없으면 0.0 으로 넘겨도 동작 (이 경우
    먼저 등장한 box 가 우선 유지됨).
    """
    if len(boxes) != len(scores):
        raise ValueError("boxes and scores must have the same length")

    # score 내림차순 (동점이면 원래 순서 유지) 으로 후보 정렬
    order = sorted(range(len(boxes)), key=lambda i: (-scores[i], i))

    kept: list[int] = []
    kept_boxes: list[Bbox] = []
    for idx in order:
        box = boxes[idx]
        if any(bbox_iou(box, kb) > iou_threshold for kb in kept_boxes):
            continue
        kept.append(idx)
        kept_boxes.append(box)

    return sorted(kept)
