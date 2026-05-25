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

from collections.abc import Iterable, Sequence
from typing import Protocol

from app.geometry.matching import (
    Bbox,
    bbox_orientation,
    segment_orientation,
)

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
def _coord_extent(walls: Sequence[_WallLike]) -> float:
    """wall 좌표들의 bounding box 긴 변. tolerance 산출 기준."""
    xs: list[float] = []
    ys: list[float] = []
    for w in walls:
        xs.extend((w.x1, w.x2))
        ys.extend((w.y1, w.y2))
    if not xs:
        return 0.0
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _set_wall(w: _WallLike, x1: float, y1: float, x2: float, y2: float) -> None:
    w.x1, w.y1, w.x2, w.y2 = float(x1), float(y1), float(x2), float(y2)


# ============================================================
# 1. collinear wall 잇기
# ============================================================
def bridge_collinear_walls(
    walls: Iterable[_WallLike],
    *,
    axis_ratio: float = DEFAULT_COLLINEAR_AXIS_RATIO,
    gap_ratio: float = DEFAULT_COLLINEAR_GAP_RATIO,
) -> list[_WallLike]:
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

    horizontals: list[_WallLike] = []
    verticals: list[_WallLike] = []
    others: list[_WallLike] = []
    for w in walls:
        orient = segment_orientation(w.x1, w.y1, w.x2, w.y2)
        if orient == "horizontal":
            horizontals.append(w)
        elif orient == "vertical":
            verticals.append(w)
        else:
            others.append(w)

    result: list[_WallLike] = []
    result.extend(_bridge_axis(horizontals, axis="h", axis_tol=axis_tol, max_gap=max_gap))
    result.extend(_bridge_axis(verticals, axis="v", axis_tol=axis_tol, max_gap=max_gap))
    result.extend(others)
    return result


def _bridge_axis(
    walls: Sequence[_WallLike], *, axis: str, axis_tol: float, max_gap: float
) -> list[_WallLike]:
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
    walls: Iterable[_WallLike],
    *,
    snap_ratio: float = DEFAULT_ENDPOINT_SNAP_RATIO,
) -> list[_WallLike]:
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
def project_openings_onto_walls(
    openings: Iterable[_OpeningLike], walls: Iterable[_WallLike]
) -> int:
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


# ============================================================
# 4. 개구부(문/창) 를 벽 증거로 → 벽 중심선 조각 합성
# ============================================================
def synthesize_opening_wall_segments(
    opening_bboxes: Iterable[Bbox],
    walls: Sequence[_WallLike],
    *,
    perp_ratio: float = 0.04,
    reach_ratio: float = 0.10,
    min_perp_px: float = 15.0,
) -> list[tuple[float, float, float, float]]:
    """문/창 bbox 를 "여기 벽이 지나간다" 는 증거로 보고 벽 중심선 조각을 합성한다.

    U-Net 은 개구부 위치에서 벽 확률이 떨어져 벽이 끊기는 경우가 흔하다. 그러면
    `polygonize` 가 방을 못 닫아(내벽이 사라진 것처럼) 인접 방이 하나로 합쳐진다.
    개구부는 정의상 벽에 박혀 있으므로, 그 자리에 짧은 중심선 조각을 끼워 넣으면
    끊긴 양쪽 벽을 이어 방 폐합률을 높인다.

    ⚠️ 반환된 조각은 **방 추출 입력에만** 더해야 한다 (영속 wall 에 넣으면 문 위에
    벽이 중복 렌더됨). 호출자가 분리 책임.

    축 결정 — bbox 방향은 door swing 때문에 신뢰 불가(host 벽과 직교로 보일 수 있음).
    그래서 **host 벽을 먼저 찾고 그 벽의 방향을 축으로** 삼는다:
      - 각 H/V wall 의 무한직선까지의 수직거리(perp_off) + 선분 끝까지의 along-axis
        거리(along_gap) 계산.
      - perp_off ≤ perp_tol, along_gap ≤ reach_tol 이면 host 후보. perp_off 최소 채택.
      - host 가 잡히면 그 벽과 collinear(같은 perp) 하게, bbox 의 host-축 길이만큼 조각 생성.
      - 못 찾으면 bbox 가 명확히 길쭉할 때만 그 축으로 fallback (ambiguous 는 skip).

    좌표 단위: 픽셀 (fusion 파이프라인 기준).
    반환: (x1, y1, x2, y2) 중심선 좌표 리스트.
    """
    walls = list(walls)
    extent = _coord_extent(walls)

    segments: list[tuple[float, float, float, float]] = []
    for bbox in opening_bboxes:
        x1, y1, x2, y2 = (float(v) for v in bbox)
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        bw, bh = abs(x2 - x1), abs(y2 - y1)
        if bw <= 0.0 and bh <= 0.0:
            continue

        # perp_tol 은 door swing 으로 bbox 중심이 벽선에서 떨어진 만큼 흡수해야 함 →
        # bbox 짧은 변 절반도 하한으로 반영.
        perp_tol = max(min_perp_px, extent * perp_ratio, 0.5 * min(bw, bh))
        reach_tol = max(extent * reach_ratio, 2.0 * max(bw, bh))

        best_wall: _WallLike | None = None
        best_axis = ""
        best_perp_off = perp_tol
        for w in walls:
            o = segment_orientation(w.x1, w.y1, w.x2, w.y2)
            if o == "horizontal":
                wp = (w.y1 + w.y2) / 2.0
                perp_off = abs(cy - wp)
                lo, hi = sorted((w.x1, w.x2))
                along_gap = 0.0 if lo <= cx <= hi else min(abs(cx - lo), abs(cx - hi))
            elif o == "vertical":
                wp = (w.x1 + w.x2) / 2.0
                perp_off = abs(cx - wp)
                lo, hi = sorted((w.y1, w.y2))
                along_gap = 0.0 if lo <= cy <= hi else min(abs(cy - lo), abs(cy - hi))
            else:
                continue  # diagonal/degenerate → 축 모호, 제외
            if perp_off <= best_perp_off and along_gap <= reach_tol:
                best_perp_off = perp_off
                best_wall = w
                best_axis = o

        if best_wall is not None:
            if best_axis == "horizontal" and bw > 0.0:
                perp = (best_wall.y1 + best_wall.y2) / 2.0
                half = bw / 2.0
                segments.append((cx - half, perp, cx + half, perp))
            elif best_axis == "vertical" and bh > 0.0:
                perp = (best_wall.x1 + best_wall.x2) / 2.0
                half = bh / 2.0
                segments.append((perp, cy - half, perp, cy + half))
            continue

        # fallback: host 벽 못 찾음 → bbox 가 명확히 길쭉할 때만 그 축으로.
        op_orient = bbox_orientation(x1, y1, x2, y2)
        if op_orient == "horizontal" and bw > 0.0:
            half = bw / 2.0
            segments.append((cx - half, cy, cx + half, cy))
        elif op_orient == "vertical" and bh > 0.0:
            half = bh / 2.0
            segments.append((cx, cy - half, cx, cy + half))

    return segments


# ============================================================
# 5. 치수선 그리드 tick → (게이팅) 누락 칸막이 복구
# ============================================================
def _cluster_ticks(values: Iterable[float], tol: float) -> list[float]:
    """가까운 tick 값들을 하나로 합침 (정렬 후 tol 이내 중복 제거)."""
    out: list[float] = []
    for v in sorted(values):
        if out and abs(v - out[-1]) <= tol:
            continue
        out.append(v)
    return out


def synthesize_partition_walls_from_ticks(
    vtick_xs: Iterable[float],   # 벽 없는 세로 그리드라인 x (수평 치수선 tick)
    htick_ys: Iterable[float],   # 벽 없는 가로 그리드라인 y (수직 치수선 tick)
    walls: Sequence[_WallLike],
    *,
    tol_ratio: float = 0.02,
    min_tol_px: float = 12.0,
) -> list[tuple[float, float, float, float]]:
    """치수선 그리드 tick + 직교벽 끝점 = 누락 칸막이 증거 → 칸막이 조각 합성.

    게이팅(교차증거 필수): tick 자리에 직교벽의 **끝점**이 가까이 있을 때만 합성.
      - 가로벽이 허공에서 끝남(xlo/xhi ≈ T) = 거기 세로 칸막이가 만나야 함
      - + 치수 tick = 그리드 경계
      두 독립 증거가 겹칠 때만 → 과분할 위험 ↓. 끝점에서 반대편 직교벽까지 연결.

    개구부 앵커(synthesize_opening_wall_segments)와 상보적 — 이쪽은 "벽 끝점"
    증거를 쓰므로 개구부 신호와 중복되지 않는다.

    ⚠️ 개구부 조각과 동일하게 **방 추출 입력 전용**. 영속 벽엔 넣지 말 것.
    반환: (x1, y1, x2, y2) 중심선 좌표 리스트.
    """
    walls = list(walls)
    extent = _coord_extent(walls)
    tol = max(min_tol_px, extent * tol_ratio)

    hwalls: list[tuple[float, float, float]] = []  # (xlo, xhi, ymid)
    vwalls: list[tuple[float, float, float]] = []  # (ylo, yhi, xmid)
    for w in walls:
        o = segment_orientation(w.x1, w.y1, w.x2, w.y2)
        if o == "horizontal":
            hwalls.append((min(w.x1, w.x2), max(w.x1, w.x2), (w.y1 + w.y2) / 2.0))
        elif o == "vertical":
            vwalls.append((min(w.y1, w.y2), max(w.y1, w.y2), (w.x1 + w.x2) / 2.0))

    segments: list[tuple[float, float, float, float]] = []

    # 세로 칸막이: 세로 tick x=T, 가로벽 끝점이 T 근처
    for t in _cluster_ticks(vtick_xs, tol):
        anchors = [ym for (xlo, xhi, ym) in hwalls if min(abs(xlo - t), abs(xhi - t)) <= tol]
        if not anchors:
            continue
        covering = [ym for (xlo, xhi, ym) in hwalls if xlo - tol <= t <= xhi + tol]
        ay = anchors[0]
        others = [y for y in covering if abs(y - ay) > tol]
        if not others:
            continue
        by = min(others, key=lambda y: abs(y - ay))
        segments.append((t, min(ay, by), t, max(ay, by)))

    # 가로 칸막이: 가로 tick y=T, 세로벽 끝점이 T 근처
    for t in _cluster_ticks(htick_ys, tol):
        anchors = [xm for (ylo, yhi, xm) in vwalls if min(abs(ylo - t), abs(yhi - t)) <= tol]
        if not anchors:
            continue
        covering = [xm for (ylo, yhi, xm) in vwalls if ylo - tol <= t <= yhi + tol]
        ax = anchors[0]
        others = [x for x in covering if abs(x - ax) > tol]
        if not others:
            continue
        bx = min(others, key=lambda x: abs(x - ax))
        segments.append((min(ax, bx), t, max(ax, bx), t))

    return segments


# ============================================================
# 6. 문/창 자리에서 벽 절단 (방 추출 끝난 뒤 마지막 단계)
# ============================================================
def cut_walls_at_openings(
    walls: Sequence[_WallLike],
    openings: Iterable[_OpeningLike],
    *,
    min_seg_px: float = 3.0,
) -> list[_WallLike]:
    """opening(문/창) 이 박힌 벽을 opening 폭만큼 잘라 gap 을 낸다 (문/창 자리엔 벽 없음).

    ⚠️ 반드시 **방 추출이 끝난 뒤** 최종 단계에서 호출 — 연속 벽으로 방을 닫은 다음
    벽만 자르므로 방 폐합엔 영향 없음. (먼저 자르면 polygonize 가 방을 못 닫음)

    opening.wall_ref 가 가리키는 벽을 그 opening 의 (벽 축 투영) 구간만큼 제거하고
    남는 구간들을 새 wall 로. 첫 조각은 원래 id 유지 → 기존 opening 참조 안 깨짐.
    """
    walls = list(walls)
    by_id = {str(getattr(w, "id", "")): w for w in walls}

    # 벽별로 잘라낼 구간(벽 축 좌표) 모으기
    cuts: dict[str, list[tuple[float, float]]] = {}
    for op in openings:
        wid = getattr(op, "wall_ref", None)
        if wid is None:
            continue
        w = by_id.get(str(wid))
        if w is None:
            continue
        orient = segment_orientation(w.x1, w.y1, w.x2, w.y2)
        ocx = (op.x1 + op.x2) / 2.0
        ocy = (op.y1 + op.y2) / 2.0
        ow = max(abs(op.x2 - op.x1), abs(op.y2 - op.y1))  # 개구부 폭(긴 축)
        if orient == "horizontal":
            lo, hi = ocx - ow / 2.0, ocx + ow / 2.0
        elif orient == "vertical":
            lo, hi = ocy - ow / 2.0, ocy + ow / 2.0
        else:
            continue
        cuts.setdefault(str(wid), []).append((min(lo, hi), max(lo, hi)))

    def _clone(w, x1, y1, x2, y2, new_id):
        mc = getattr(w, "model_copy", None)
        if mc is not None:
            return mc(update={"id": new_id, "x1": float(x1), "y1": float(y1),
                              "x2": float(x2), "y2": float(y2)})
        import copy
        nw = copy.copy(w)
        nw.id, nw.x1, nw.y1, nw.x2, nw.y2 = new_id, float(x1), float(y1), float(x2), float(y2)
        return nw

    result: list[_WallLike] = []
    for w in walls:
        wid = str(getattr(w, "id", ""))
        if wid not in cuts:
            result.append(w)
            continue
        orient = segment_orientation(w.x1, w.y1, w.x2, w.y2)
        if orient == "horizontal":
            a0, a1, perp, horiz = w.x1, w.x2, (w.y1 + w.y2) / 2.0, True
        elif orient == "vertical":
            a0, a1, perp, horiz = w.y1, w.y2, (w.x1 + w.x2) / 2.0, False
        else:
            result.append(w)
            continue
        lo_end, hi_end = min(a0, a1), max(a0, a1)
        intervals = sorted(
            (max(lo_end, c0), min(hi_end, c1))
            for c0, c1 in cuts[wid] if c1 > lo_end and c0 < hi_end
        )
        # 남는 구간 = [lo_end, hi_end] − intervals
        segs: list[tuple[float, float]] = []
        cur = lo_end
        for c0, c1 in intervals:
            if c0 - cur > min_seg_px:
                segs.append((cur, c0))
            cur = max(cur, c1)
        if hi_end - cur > min_seg_px:
            segs.append((cur, hi_end))

        for i, (s, e) in enumerate(segs):
            new_id = wid if i == 0 else f"{wid}_{i}"
            if horiz:
                result.append(_clone(w, s, perp, e, perp, new_id))
            else:
                result.append(_clone(w, perp, s, perp, e, new_id))
    return result
