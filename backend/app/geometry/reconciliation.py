"""Scene reconciliation — wall_extraction + opening 탐지 결과의 정합성 보정.

fusion_service 가 walls/openings 를 만든 직후 호출하는 "후-후처리".
좌표 단위: 픽셀 (fusion 파이프라인 기준). 미터 변환은 이후 save_scene_draft 책임.

보정 3종:
  1. bridge_collinear_walls      — 같은 직선 위 끊긴 wall 들을 하나로 연결 (방 폐합률 ↑)
  2. snap_wall_endpoints         — 가까운 wall 끝점들을 공유 코너로 스냅
  3. project_openings_onto_walls — opening 을 매칭된 wall 중심선 위로 투영 (문/창 정렬)

tolerance 는 wall 좌표 전체 extent 대비 비율로 자동 산출 — 이미지 해상도에 무관.
"""
from __future__ import annotations

from typing import Protocol

from app.geometry.matching import segment_orientation

# tolerance 비율 (wall 좌표 전체 extent 대비)
DEFAULT_COLLINEAR_AXIS_RATIO = 0.012   # collinear 판정: 수직(perp) 위치 차이 허용
DEFAULT_COLLINEAR_GAP_RATIO = 0.06     # 이을 수 있는 최대 along-axis 틈
DEFAULT_ENDPOINT_SNAP_RATIO = 0.02     # 끝점 스냅 반경


class _WallLike(Protocol):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float


class _OpeningLike(Protocol):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    wall_ref: str | None


# ============================================================
# 공통 헬퍼
# ============================================================
def _coord_extent(walls) -> float:
    """wall 좌표들의 bounding box 긴 변. tolerance 산출 기준."""
    xs: list[float] = []
    ys: list[float] = []
    for w in walls:
        xs.extend((w.x1, w.x2))
        ys.extend((w.y1, w.y2))
    if not xs:
        return 0.0
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _set_wall(w, x1: float, y1: float, x2: float, y2: float) -> None:
    w.x1, w.y1, w.x2, w.y2 = float(x1), float(y1), float(x2), float(y2)


# ============================================================
# 1. collinear wall 잇기
# ============================================================
def bridge_collinear_walls(
    walls,
    *,
    axis_ratio: float = DEFAULT_COLLINEAR_AXIS_RATIO,
    gap_ratio: float = DEFAULT_COLLINEAR_GAP_RATIO,
) -> list:
    """같은 직선 위 끊긴 wall 들을 하나로 병합.

    horizontal 끼리 / vertical 끼리만 처리. diagonal/ambiguous 는 그대로 통과.
    병합된 wall 은 체인의 첫 wall 의 id 를 유지 (assign_wall_refs 가 이후 실행되므로
    사라진 id 를 참조할 위험 없음).

    반환: 새 wall 리스트 (입력 리스트는 수정하지 않지만 wall 객체는 in-place 변경됨).
    """
    walls = list(walls)
    if len(walls) < 2:
        return walls
    extent = _coord_extent(walls)
    if extent <= 0:
        return walls

    axis_tol = extent * axis_ratio
    max_gap = extent * gap_ratio

    horizontals: list = []
    verticals: list = []
    others: list = []
    for w in walls:
        orient = segment_orientation(w.x1, w.y1, w.x2, w.y2)
        if orient == "horizontal":
            horizontals.append(w)
        elif orient == "vertical":
            verticals.append(w)
        else:
            others.append(w)

    result: list = []
    result.extend(_bridge_axis(horizontals, axis="h", axis_tol=axis_tol, max_gap=max_gap))
    result.extend(_bridge_axis(verticals, axis="v", axis_tol=axis_tol, max_gap=max_gap))
    result.extend(others)
    return result


def _bridge_axis(walls, *, axis: str, axis_tol: float, max_gap: float) -> list:
    """같은 축(h/v) wall 들을 perp 위치로 그룹핑 후 collinear gap 메우기."""
    if not walls:
        return []

    # (perp, lo, hi, wall): axis='h' → perp=avg y, lo/hi=min/max x. 'v' 는 반대.
    items: list[list] = []
    for w in walls:
        if axis == "h":
            perp = (w.y1 + w.y2) / 2.0
            lo, hi = sorted((w.x1, w.x2))
        else:
            perp = (w.x1 + w.x2) / 2.0
            lo, hi = sorted((w.y1, w.y2))
        items.append([perp, lo, hi, w])

    items.sort(key=lambda it: (it[0], it[1]))

    used = [False] * len(items)
    result: list = []

    for i in range(len(items)):
        if used[i]:
            continue
        perp_i = items[i][0]
        group = [items[i]]
        used[i] = True
        # 같은 perp 밴드 (= 같은 직선) 후보 흡수. wall 수가 적어 O(n²) 허용.
        for j in range(i + 1, len(items)):
            if used[j]:
                continue
            if abs(items[j][0] - perp_i) <= axis_tol:
                group.append(items[j])
                used[j] = True

        # group 을 along-axis 로 정렬 → gap 작은 것끼리 체인 분리
        group.sort(key=lambda it: it[1])
        chains: list[list] = []
        chain = [group[0]]
        for k in range(1, len(group)):
            prev_hi = max(it[2] for it in chain)
            this_lo = group[k][1]
            if this_lo - prev_hi <= max_gap:
                chain.append(group[k])
            else:
                chains.append(chain)
                chain = [group[k]]
        chains.append(chain)

        # 각 체인 → 하나의 wall (첫 wall id 유지)
        for chn in chains:
            lo = min(it[1] for it in chn)
            hi = max(it[2] for it in chn)
            perp = sum(it[0] for it in chn) / len(chn)
            base_wall = chn[0][3]
            if axis == "h":
                _set_wall(base_wall, lo, perp, hi, perp)
            else:
                _set_wall(base_wall, perp, lo, perp, hi)
            result.append(base_wall)

    return result


# ============================================================
# 2. wall 끝점 스냅 (코너 폐합)
# ============================================================
def snap_wall_endpoints(
    walls,
    *,
    snap_ratio: float = DEFAULT_ENDPOINT_SNAP_RATIO,
) -> list:
    """가까운 wall 끝점들을 공유 좌표로 스냅.

    union-find 로 거리 < tol 인 끝점들을 클러스터링한 뒤 각 클러스터 centroid 로 스냅.
    `_snap_endpoints` (wall_extraction) 의 pairwise midpoint drift 문제를 회피.

    반환: 입력 wall 리스트 (wall 객체는 in-place 변경됨).
    """
    walls = list(walls)
    if len(walls) < 2:
        return walls
    extent = _coord_extent(walls)
    if extent <= 0:
        return walls

    tol_sq = (extent * snap_ratio) ** 2

    # 끝점: [x, y, wall_idx, which(0|1)]
    pts: list[list] = []
    for wi, w in enumerate(walls):
        pts.append([w.x1, w.y1, wi, 0])
        pts.append([w.x2, w.y2, wi, 1])

    n = len(pts)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            dx = pts[i][0] - pts[j][0]
            dy = pts[i][1] - pts[j][1]
            if dx * dx + dy * dy <= tol_sq:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    for members in clusters.values():
        if len(members) < 2:
            continue
        cx = sum(pts[m][0] for m in members) / len(members)
        cy = sum(pts[m][1] for m in members) / len(members)
        for m in members:
            _, _, wi, which = pts[m]
            w = walls[wi]
            if which == 0:
                w.x1, w.y1 = float(cx), float(cy)
            else:
                w.x2, w.y2 = float(cx), float(cy)

    return walls


# ============================================================
# 3. opening 을 wall 중심선 위로 투영
# ============================================================
def project_openings_onto_walls(openings, walls) -> int:
    """wall_ref 가 세팅된 opening 을 매칭된 wall 중심선 위로 투영.

    opening bbox 의 중심을 wall 선분 위로 수직투영 → 그 점을 중심으로,
    opening 의 긴 축 길이를 유지하면서 wall 방향에 정렬된 bbox 로 재배치.
    `assign_wall_refs` 이후에 호출해야 함 (wall_ref 가 채워진 상태 가정).

    in-place 로 opening.x1..y2 수정. 반환: 투영한 opening 수.
    """
    wall_by_id = {str(w.id): w for w in walls}
    projected = 0

    for op in openings:
        if op.wall_ref is None:
            continue
        wall = wall_by_id.get(str(op.wall_ref))
        if wall is None:
            continue

        # opening bbox
        cx = (op.x1 + op.x2) / 2.0
        cy = (op.y1 + op.y2) / 2.0
        bw = abs(op.x2 - op.x1)
        bh = abs(op.y2 - op.y1)
        length = max(bw, bh)          # opening 긴 축 = 폭
        thin = max(min(bw, bh), 1.0)  # 짧은 축 (최소 1px)

        # wall 선분 위로 중심 C 투영
        ax, ay, bx, by = wall.x1, wall.y1, wall.x2, wall.y2
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= 1e-9:
            continue  # degenerate wall
        t = ((cx - ax) * dx + (cy - ay) * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))
        px = ax + t * dx
        py = ay + t * dy

        # wall 단위 방향 + 수직 방향
        seg_len = seg_len_sq ** 0.5
        ux, uy = dx / seg_len, dy / seg_len
        nx, ny = -uy, ux

        # P 중심, wall 방향으로 length, 수직으로 thin 인 bbox
        half = length / 2.0
        ht = thin / 2.0
        e1x, e1y = px - ux * half, py - uy * half
        e2x, e2y = px + ux * half, py + uy * half
        xs = (e1x + nx * ht, e1x - nx * ht, e2x + nx * ht, e2x - nx * ht)
        ys = (e1y + ny * ht, e1y - ny * ht, e2y + ny * ht, e2y - ny * ht)

        op.x1, op.y1 = float(min(xs)), float(min(ys))
        op.x2, op.y2 = float(max(xs)), float(max(ys))
        projected += 1

    return projected
