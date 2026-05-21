import cv2
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Any, Tuple
from app.core.settings import MASK_DIR


@dataclass
class PostprocessMetadata:
    """§69 wall postprocess 결과 metadata.

    응답 / `summary_json["wall_postprocess"]` 영속화 / 디버깅 라우터에서 동일하게 사용.
    `applied=False` 면 threshold scoring 비활성 (image_path 없음, helper import 실패 등).
    """
    applied: bool
    selected_threshold: float | None = None
    threshold_candidates: list[float] = field(default_factory=list)
    scores: list[dict] = field(default_factory=list)  # ThresholdScore.to_dict()
    ocr_regions_count: int = 0
    line_segments_count: int = 0       # 벽 점수에 실제 사용된 wall_candidate 선분 수
    dimension_lines_excluded: int = 0  # 치수선으로 분류돼 벽 후보에서 제외된 선분 수
    # OCR 진단용 원본 entries (각 항목: text/bbox/confidence/parsed_meters/parse_confidence).
    # "OCR 자체 실패" vs "OCR 성공했지만 parser 가 거부" vs "parse 됐지만 매칭 실패" 분리용.
    ocr_entries: list[dict] = field(default_factory=list)
    # 치수 OCR ↔ 벽 매칭 결과 (scoring 단계에서는 dim_entries 만 추출, 매칭은 후처리 후).
    dimension_entries_count: int = 0     # 치수로 파싱된 OCR 항목 수
    dimension_matches: list[dict] = field(default_factory=list)  # DimensionMatch.to_dict()
    scale_estimate: dict | None = None   # ScaleEstimate.to_dict() — OCR 기반 scale (None 이면 fallback 필요)
    fallback_reason: str | None = None   # applied=False 일 때 사유
    debug_dir: str | None = None         # per-job 디버그 이미지 디렉토리 (있을 때)

    # Priors source tracking — None vs [] 구분.
    # "ai_service"        : AI 가 priors 제공 (빈 list 든 채워진 list 든)
    # "backend_fallback"  : AI 가 안 줘서 backend 가 자체 OCR/line 실행
    # "none"              : 둘 다 못 함 (image_path 없거나 실패)
    ocr_priors_source: str = "none"
    line_priors_source: str = "none"
    fallback_used: bool = False           # 둘 중 하나라도 backend_fallback 이면 True

    # 좌표계 진단 — 배경 이미지 ↔ 벽 정렬 디버깅용.
    # prob_map 원본 shape, source image shape, 좌표 통일 resize 여부.
    # 이미지가 벽과 어긋나면 여기서 dims 불일치/resize 누락 확인.
    prob_shape: list[int] | None = None      # [H, W] of loaded prob_map (resize 전)
    image_shape: list[int] | None = None     # [H, W] of source image (Phase A 에서 읽음)
    coord_resized: bool = False              # prob_map → image dims resize 발생 여부
    coord_aligned: bool = False              # 최종 prob 이 image 좌표계와 정렬됐는지

    # prior-guided line fusion 진단 — AI 원본 Hough line prior 를 prob 로 검증해 최종
    # 벽 후보에 합친 결과. wall_candidate 만 대상, corridor mean+coverage 통과만 채택.
    prior_line_candidates_count: int = 0       # wall_candidate prior 입력 수
    prior_line_accepted_count: int = 0         # prob 검증 통과해 fusion 된 수
    prior_line_rejected_low_prob_count: int = 0  # mean prob 미달 탈락
    prior_line_rejected_coverage_count: int = 0  # coverage 미달 탈락
    prior_line_fusion_applied: bool = False    # fusion 단계 실행 여부

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "selected_threshold": self.selected_threshold,
            "threshold_candidates": list(self.threshold_candidates),
            "scores": list(self.scores),
            "ocr_regions_count": self.ocr_regions_count,
            "line_segments_count": self.line_segments_count,
            "dimension_lines_excluded": self.dimension_lines_excluded,
            "ocr_entries": list(self.ocr_entries),
            "dimension_entries_count": self.dimension_entries_count,
            "dimension_matches": list(self.dimension_matches),
            "scale_estimate": self.scale_estimate,
            "fallback_reason": self.fallback_reason,
            "debug_dir": self.debug_dir,
            "ocr_priors_source": self.ocr_priors_source,
            "line_priors_source": self.line_priors_source,
            "fallback_used": self.fallback_used,
            "prob_shape": self.prob_shape,
            "image_shape": self.image_shape,
            "coord_resized": self.coord_resized,
            "coord_aligned": self.coord_aligned,
            "prior_line_candidates_count": self.prior_line_candidates_count,
            "prior_line_accepted_count": self.prior_line_accepted_count,
            "prior_line_rejected_low_prob_count": self.prior_line_rejected_low_prob_count,
            "prior_line_rejected_coverage_count": self.prior_line_rejected_coverage_count,
            "prior_line_fusion_applied": self.prior_line_fusion_applied,
        }


@dataclass
class WallExtractionResult:
    """`execute_from_prob_map` 반환값. walls 좌표 + postprocess metadata 묶음."""
    walls: list[list[float]]
    postprocess: PostprocessMetadata


class WallExtractor:
    def __init__(self):
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    def _resolve_debug_dir(self, debug_dir: Path | None) -> Path:
        """디버그 이미지 저장 경로. 명시되면 그 디렉토리, 아니면 MASK_DIR fallback."""
        target = Path(debug_dir) if debug_dir is not None else MASK_DIR
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ── 1. 전처리 ─────────────────────────────────────────────────────────
    def _preprocess(self, mask: np.ndarray, debug_dir: Path | None = None) -> np.ndarray:
        """Open(작게)으로 노이즈만 제거 → 수평/수직 Close 따로 적용해 합집합.

        이전엔 큰 정사각형(k*2) Close 로 인접 평행 벽을 뭉치게 했는데, 얇은 내부 벽이
        사라지는 문제 있어서 H/V 분리:
          - 수평 close (k_close, 1) → 가로 벽 안의 작은 끊김만 메움
          - 수직 close (1, k_close) → 세로 벽 안의 작은 끊김만 메움
          - 두 결과 OR → H/V 벽 모두 보존하되 perpendicular gap bridging 회피
        """
        _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        h, w = binary.shape

        # Open: 노이즈 제거용 작은 커널 (이전 0.01 → 0.003 으로 축소).
        k_open = max(2, int(min(h, w) * 0.003))
        open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_open, k_open))
        clean = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_kernel)

        # Close: H/V 분리해서 각자의 끊김만 메움.
        k_close = max(5, int(min(h, w) * 0.008))
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_close, 1))
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, k_close))
        h_close = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, h_kernel)
        v_close = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, v_kernel)
        clean = cv2.bitwise_or(h_close, v_close)

        out_dir = self._resolve_debug_dir(debug_dir)
        cv2.imwrite(str(out_dir / "debug_edges.png"), clean)
        return clean

    # ── 2. Skeleton ───────────────────────────────────────────────────────
    def _skeletonize(self, edges: np.ndarray, prob_map=None, conf_floor: float = 0.4, debug_dir: Path | None = None) -> np.ndarray:
        from skimage.morphology import thin

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(edges)
        clean = np.zeros_like(edges)
        h, w = edges.shape
        min_area = h * w * 0.001
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] > min_area:
                clean[labels == i] = 255

        binary = (clean > 0).astype(bool)
        thinned = thin(binary).astype(np.uint8) * 255

        # prob_map 있으면 저확률 픽셀 제거. conf_floor 는 **선택된 threshold** 를 받음.
        # (예전엔 0.4 하드코딩 → mask 가 prob>thr(예 0.25)여도 prob 0.25~0.4 벽은 여기서
        #  지워져 "빨강인데 선 안 됨". 이제 mask 와 같은 floor 라 일관됨.)
        if prob_map is not None:
            conf_mask = (prob_map > conf_floor)
            thinned = ((thinned > 0) & conf_mask).astype(np.uint8) * 255

        out_dir = self._resolve_debug_dir(debug_dir)
        cv2.imwrite(str(out_dir / "debug_skeleton.png"), thinned)
        return thinned
    
    def _filter_by_confidence(self, lines: List, prob_map: np.ndarray, min_conf=0.6) -> List:
        h, w = prob_map.shape
        result = []
        for x1, y1, x2, y2 in lines:
            n = max(int(np.hypot(x2-x1, y2-y1)), 1)
            xs = np.clip(np.linspace(x1, x2, n).astype(int), 0, w-1)
            ys = np.clip(np.linspace(y1, y2, n).astype(int), 0, h-1)
            if prob_map[ys, xs].mean() >= min_conf:
                result.append([x1, y1, x2, y2])
        return result

    def _filter_line_priors_by_probability(
        self,
        line_priors,
        prob_map: np.ndarray,
        threshold: float,
        band_px: int = 4,
        min_run_px: float = 25.0,
        max_gap_px: float = 40.0,
        meta: "PostprocessMetadata | None" = None,
    ) -> List[List[float]]:
        """AI 원본 Hough line 을 따라 'prob 위에 얹힌 구간'만 추출 (segment 단위).

        whole-line coverage 는 patchy U-Net 에선 외벽(일부만 prob)을 떨구거나, 느슨하면
        방 가로지르는 노이즈를 통과시킨다. 그래서 선을 따라가며:
          1) wall_mask = prob>threshold 를 band_px dilate (선↔prob 오프셋 흡수)
          2) 선 1px 샘플별 on-wall 여부 → 연속 on-wall run 추출 (max_gap_px 이하 끊김은
             bridge: 문/창·U-Net dropout 메움)
          3) min_run_px 이상인 run 만 벽 후보 sub-segment 로 채택
        → patchy 외벽은 긴 on-wall run 으로 복원, 방 가로지르는 선은 교차점의 짧은 run
           뿐이라 min_run 미달로 탈락.
        """
        accepted: List[List[float]] = []
        cand = acc_lines = rej = seg_n = 0
        h, w = prob_map.shape[:2]
        wall = (prob_map > threshold).astype(np.uint8)
        k = 2 * max(1, int(band_px)) + 1
        wall_dil = cv2.dilate(wall, np.ones((k, k), np.uint8))
        for p in line_priors or []:
            if p.get("kind", "wall_candidate") != "wall_candidate":
                continue
            try:
                x1, y1 = float(p["x1"]), float(p["y1"])
                x2, y2 = float(p["x2"]), float(p["y2"])
            except (KeyError, TypeError, ValueError):
                continue
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if length < min_run_px:
                continue
            cand += 1
            n = max(int(length), 1)
            xs = np.clip(np.linspace(x1, x2, n).astype(int), 0, w - 1)
            ys = np.clip(np.linspace(y1, y2, n).astype(int), 0, h - 1)
            on = wall_dil[ys, xs] > 0  # 샘플별 on-wall (≈1px/sample)
            runs = self._onwall_runs(on, max_gap=int(max_gap_px))
            kept = False
            for a, b in runs:
                if (b - a) >= min_run_px:
                    accepted.append([float(xs[a]), float(ys[a]),
                                     float(xs[b]), float(ys[b])])
                    seg_n += 1
                    kept = True
            if kept:
                acc_lines += 1
            else:
                rej += 1
        if meta is not None:
            meta.prior_line_candidates_count = cand
            meta.prior_line_accepted_count = seg_n          # 채택된 sub-segment 수
            meta.prior_line_rejected_low_prob_count = 0
            meta.prior_line_rejected_coverage_count = rej   # on-wall run 없던 선 수
            meta.prior_line_fusion_applied = line_priors is not None
        return accepted

    @staticmethod
    def _onwall_runs(on: np.ndarray, max_gap: int) -> List[tuple]:
        """bool 배열에서 True run 추출 — max_gap 이하 False 끊김은 이어붙임(bridge).

        반환: (start_idx, end_idx) 리스트.
        """
        n = len(on)
        runs: List[tuple] = []
        i = 0
        while i < n:
            if not on[i]:
                i += 1
                continue
            j = i + 1
            while j < n:
                if on[j]:
                    j += 1
                    continue
                # False 구간 — max_gap 이내에 다음 True 있으면 bridge
                k = j
                while k < n and not on[k]:
                    k += 1
                if k < n and (k - j) <= max_gap:
                    j = k
                else:
                    break
            runs.append((i, j - 1))
            i = j
        return runs


    # ── 3. 선분 검출 ──────────────────────────────────────────────────────
    def _detect_lines(self, skeleton: np.ndarray) -> List[List[float]]:
        h, w = skeleton.shape
        lines = cv2.HoughLinesP(
            skeleton,
            rho=1,
            theta=np.pi / 180,
            threshold=20,                        
            minLineLength=int(min(h, w) * 0.03),
            maxLineGap=int(min(h, w) * 0.06),   
        )
        if lines is None:
            return []
        return [l[0].tolist() for l in lines]

    # ── 4. 수평/수직 필터 ─────────────────────────────────────────────────
    def _filter_hv(self, lines: List, angle_thresh=15.0) -> List:
        result = []
        for x1, y1, x2, y2 in lines:
            angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
            is_h = angle < angle_thresh or angle > (180 - angle_thresh)
            is_v = abs(angle - 90) < angle_thresh
            if is_h or is_v:
                result.append([x1, y1, x2, y2])
        return result

    def _snap_to_hv(self, lines: List) -> List:
        result = []
        for x1, y1, x2, y2 in lines:
            dx = x2 - x1
            dy = y2 - y1
            angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
            
            is_h = angle < 45 or angle > 135  
            
            if is_h:
                avg_y = (y1 + y2) / 2
                result.append([x1, avg_y, x2, avg_y])
            else:
                avg_x = (x1 + x2) / 2
                result.append([avg_x, y1, avg_x, y2])
        return result

    def _snap_endpoints(self, lines: List, tol: float = 15.0) -> List:
        pts = []
        for l in lines:
            pts.append([l[0], l[1]])
            pts.append([l[2], l[3]])
        
        for i in range(len(pts)):
            for j in range(i+1, len(pts)):
                dx = pts[i][0] - pts[j][0]
                dy = pts[i][1] - pts[j][1]
                if dx*dx + dy*dy < tol*tol:
                    mx = (pts[i][0] + pts[j][0]) / 2
                    my = (pts[i][1] + pts[j][1]) / 2
                    pts[i][0] = pts[j][0] = mx
                    pts[i][1] = pts[j][1] = my
        
        result = []
        for k, l in enumerate(lines):
            result.append([pts[k*2][0], pts[k*2][1], pts[k*2+1][0], pts[k*2+1][1]])
        return result
    
    def _snap_intersections(self, lines: List, tol=20.0) -> List:
        result = [l.copy() for l in lines]

        for i in range(len(result)):
            x1, y1, x2, y2 = result[i]

            for j in range(len(result)):
                if i == j:
                    continue

                x3, y3, x4, y4 = result[j]

                # i: horizontal, j: vertical
                if abs(y1 - y2) < 5 and abs(x3 - x4) < 5:
                    ix = x3
                    iy = y1

                # i: vertical, j: horizontal
                elif abs(x1 - x2) < 5 and abs(y3 - y4) < 5:
                    ix = x1
                    iy = y3
                else:
                    continue

                # endpoint가 intersection 근처면 붙이기
                for k in [0, 2]:
                    px = result[i][k]
                    py = result[i][k+1]

                    if (px - ix)**2 + (py - iy)**2 < tol**2:
                        result[i][k] = ix
                        result[i][k+1] = iy

        return result
        
    # ── 5. 유사 선분 병합 ─────────────────────────────────────────────────
    def _merge_lines(self, lines: List, pos_thresh=30, angle_thresh=10.0) -> List:
        if not lines:
            return []

        lines = sorted(lines, key=lambda l: np.hypot(l[2] - l[0], l[3] - l[1]), reverse=True)
        used = [False] * len(lines)
        result = []

        for i in range(len(lines)):
            if used[i]:
                continue
            x1, y1, x2, y2 = lines[i]
            a1 = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
            group = [lines[i]]
            used[i] = True

            for j in range(i + 1, len(lines)):
                if used[j]:
                    continue
                x3, y3, x4, y4 = lines[j]
                a2 = np.degrees(np.arctan2(y4 - y3, x4 - x3)) % 180
                if min(abs(a1 - a2), 180 - abs(a1 - a2)) > angle_thresh:
                    continue
                if a1 < 45 or a1 > 135:
                    similar = abs((y1 + y2) / 2 - (y3 + y4) / 2) < pos_thresh
                else:
                    similar = abs((x1 + x2) / 2 - (x3 + x4) / 2) < pos_thresh
                if similar:
                    group.append(lines[j])
                    used[j] = True

            if a1 < 45 or a1 > 135:
                min_x = min([l[0] for l in group] + [l[2] for l in group])
                max_x = max([l[0] for l in group] + [l[2] for l in group])
                avg_y = sum(l[1] + l[3] for l in group) / (2 * len(group))
                result.append([float(min_x), float(avg_y), float(max_x), float(avg_y)])
            else:
                min_y = min([l[1] for l in group] + [l[3] for l in group])
                max_y = max([l[1] for l in group] + [l[3] for l in group])
                avg_x = sum(l[0] + l[2] for l in group) / (2 * len(group))
                result.append([float(avg_x), float(min_y), float(avg_x), float(max_y)])

        return result

    # ── 6. 짧은 선분 제거 ─────────────────────────────────────────────────

    def _filter_border(self, lines: List, img_shape: Tuple, margin_ratio: float = 0.01) -> List:
        """이미지 가장자리에 붙은 라인(캔버스 경계 잡힌 것) 제거."""
        h, w = img_shape[:2]
        margin = max(5, int(min(h, w) * margin_ratio))
        result = []
        for x1, y1, x2, y2 in lines:
            on_left = x1 < margin and x2 < margin
            on_right = x1 > w - margin and x2 > w - margin
            on_top = y1 < margin and y2 < margin
            on_bottom = y1 > h - margin and y2 > h - margin
            if on_left or on_right or on_top or on_bottom:
                continue
            result.append([x1, y1, x2, y2])
        return result

    def _filter_short(self, lines: List, img_shape: Tuple) -> List:
        h, w = img_shape[:2]
        if not lines:
            return lines

        lengths = [np.hypot(l[2] - l[0], l[3] - l[1]) for l in lines]
        median_len = np.median(lengths)
        min_len = max(min(h, w) * 0.03, median_len * 0.3)
        return [l for l in lines if np.hypot(l[2] - l[0], l[3] - l[1]) >= min_len]

    # ── 7. 오프닝 갭 메우기 (room 추출용) ────────────────────────────────
    def _fill_opening_gaps(self, lines: List, detections: List[Any]) -> List:
        
        if not detections:
            return lines

        result = list(lines)

        for det in detections:
            if not hasattr(det, 'class_name') or det.class_name not in ["door", "window"]:
                continue
            if not hasattr(det, 'bbox_xyxy') or det.bbox_xyxy is None:
                continue

            bx1, by1, bx2, by2 = map(float, det.bbox_xyxy)
            cx = (bx1 + bx2) / 2
            cy = (by1 + by2) / 2
            bw = bx2 - bx1
            bh = by2 - by1

            if bw >= bh:
                result.append([bx1, cy, bx2, cy])
            else:
                result.append([cx, by1, cx, by2])

        return result
    
    def _extend_dangling_endpoints(self, lines: List, max_extend=200.0, snap_tol=15.0) -> List:
       
        result = [l.copy() for l in lines]

        def is_connected(px, py, line_idx):
            for j, other in enumerate(result):
                if j == line_idx:
                    continue
                for ex, ey in [(other[0], other[1]), (other[2], other[3])]:
                    if (px - ex)**2 + (py - ey)**2 < snap_tol**2:
                        return True
            return False

        def find_nearest_line(px, py, direction, line_idx):
            best_dist, best_pt = max_extend, None
            for j, other in enumerate(result):
                if j == line_idx:
                    continue
                ox1, oy1, ox2, oy2 = other

                if direction == 'h' and abs(ox1 - ox2) < 5:
                    # 수평선 끝점 → 수직선 탐색
                    # 수직선이 py 범위를 포함하거나 snap_tol 이내면 연장 허용
                    y_min, y_max = min(oy1, oy2), max(oy1, oy2)
                    if py < y_min - snap_tol or py > y_max + snap_tol:
                        continue  # 완전히 벗어난 수직선은 제외
                    dist = abs(ox1 - px)
                    if snap_tol < dist < best_dist:
                        # 연장 후 y를 수직선 범위에 클리핑
                        clamped_y = float(np.clip(py, y_min, y_max))
                        best_dist, best_pt = dist, [ox1, clamped_y]

                elif direction == 'v' and abs(oy1 - oy2) < 5:
                    # 수직선 끝점 → 수평선 탐색
                    x_min, x_max = min(ox1, ox2), max(ox1, ox2)
                    if px < x_min - snap_tol or px > x_max + snap_tol:
                        continue  # 완전히 벗어난 수평선은 제외
                    dist = abs(oy1 - py)
                    if snap_tol < dist < best_dist:
                        clamped_x = float(np.clip(px, x_min, x_max))
                        best_dist, best_pt = dist, [clamped_x, oy1]

            return best_pt

        for i in range(len(result)):
            x1, y1, x2, y2 = result[i]
            is_h = abs(y1 - y2) < 5
            direction = 'h' if is_h else 'v'

            # 끝점1 체크
            if not is_connected(x1, y1, i):
                pt = find_nearest_line(x1, y1, direction, i)
                if pt:
                    result[i][0] = pt[0]
                    result[i][1] = pt[1]

            # 끝점2 체크
            if not is_connected(x2, y2, i):
                pt = find_nearest_line(x2, y2, direction, i)
                if pt:
                    result[i][2] = pt[0]
                    result[i][3] = pt[1]

        return result

    # ── 8. 두께 추정 ──────────────────────────────────────────────────────
    def estimate_wall_thickness(self, mask: np.ndarray, detections: List[Any]) -> float:
        samples = []
        if detections:
            for det in detections:
                if det.class_name in ["door", "window"]:
                    x1, y1, x2, y2 = map(int, det.bbox_xyxy)
                    roi = mask[y1:y2, x1:x2]
                    if roi.size == 0:
                        continue
                    dist = cv2.distanceTransform((roi > 0).astype(np.uint8), cv2.DIST_L2, 5)
                    if dist.max() > 0:
                        samples.append(dist.max())
        if not samples:
            dist_full = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
            return max(3, float(np.percentile(dist_full, 90)))
        return float(np.median(samples))

    # ── 9. 디버그 이미지 저장 ─────────────────────────────────────────────
    def _save_debug(
        self,
        skeleton: np.ndarray,
        lines: List,
        detections: List[Any] = None,
        debug_dir: Path | None = None,
    ):
        debug = cv2.cvtColor(skeleton, cv2.COLOR_GRAY2BGR)

        # 벽 선분 (주황색)
        for x1, y1, x2, y2 in lines:
            cv2.line(debug, (int(x1), int(y1)), (int(x2), int(y2)), (255, 180, 0), 2, cv2.LINE_AA)
            cv2.circle(debug, (int(x1), int(y1)), 3, (255, 255, 255), -1)
            cv2.circle(debug, (int(x2), int(y2)), 3, (255, 255, 255), -1)

        # 오프닝 오버레이: 문=초록, 창문=하늘색
        if detections:
            for det in detections:
                if not hasattr(det, 'class_name') or det.class_name not in ["door", "window"]:
                    continue
                if not hasattr(det, 'bbox_xyxy') or det.bbox_xyxy is None:
                    continue
                bx1, by1, bx2, by2 = map(int, det.bbox_xyxy)
                color = (0, 255, 0) if det.class_name == "door" else (0, 200, 255)
                cv2.rectangle(debug, (bx1, by1), (bx2, by2), color, 2)

        out_dir = self._resolve_debug_dir(debug_dir)
        cv2.imwrite(str(out_dir / "walls_overlay.png"), debug)

    # ── 10. 메인 실행 ─────────────────────────────────────────────────────
    def execute_from_mask(
        self,
        mask: np.ndarray,
        detections: List[Any] = None,
        debug_dir: Path | None = None,
    ) -> List[List[float]]:
        edges = self._preprocess(mask, debug_dir=debug_dir)
        if edges.sum() == 0:
            return []

        wall_thickness = self.estimate_wall_thickness(edges, detections or [])
        skeleton = self._skeletonize(edges, debug_dir=debug_dir)

        raw_lines = self._detect_lines(skeleton)
        hv_lines  = self._filter_hv(raw_lines)           
        merged    = self._merge_lines(hv_lines, pos_thresh=int(wall_thickness * 3.0))
        snapped   = self._snap_to_hv(merged)
        snapped   = self._filter_hv(snapped, angle_thresh=5.0)      
        snapped   = self._snap_intersections(snapped, tol=40.0)    
        snapped   = self._snap_endpoints(snapped, tol=35.0)      
        
        filtered  = self._filter_short(snapped, skeleton.shape)

        filled = self._fill_opening_gaps(filtered, detections or [])
        filled = self._merge_lines(filled, pos_thresh=int(wall_thickness * 3.0))

        # 연장
        extended = []
        for l in filled:
            p1 = np.array([l[0], l[1]])
            p2 = np.array([l[2], l[3]])
            d = np.linalg.norm(p2 - p1)
            if d > 0:
                v = (p2 - p1) / d
                extended.append([
                    float((p1 - v * 10)[0]), float((p1 - v * 10)[1]),
                    float((p2 + v * 10)[0]), float((p2 + v * 10)[1]),
                ])

        # 연장 후 재스냅 (핵심)
        extended = self._snap_intersections(extended, tol=40.0)
        extended = self._snap_endpoints(extended, tol=35.0)
        extended = self._extend_dangling_endpoints(extended, max_extend=200.0, snap_tol=15.0)

        extended = self._snap_intersections(extended, tol=20.0)


        self._save_debug(skeleton, extended, detections or [], debug_dir=debug_dir)
        return extended

    def execute_from_unet_image(
        self,
        image_path: Path,
        detections: List[Any] = None,
        debug_dir: Path | None = None,
    ) -> List[List[float]]:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return self.execute_from_mask(gray, detections, debug_dir=debug_dir)

    def execute(
        self,
        image_path: Path,
        detections: List[Any] = None,
        debug_dir: Path | None = None,
    ) -> List[List[float]]:
        return self.execute_from_unet_image(image_path, detections, debug_dir=debug_dir)

    def execute_from_prob_map(
        self,
        prob_map_path: Path,
        threshold: float = None,
        detections: List[Any] = None,
        image_path: Path | None = None,
        debug_dir: Path | None = None,
        ocr_priors: list[dict] | None = None,
        line_priors: list[dict] | None = None,
    ) -> WallExtractionResult:
        """U-Net wall probability map → walls + postprocess metadata.

        threshold 결정 우선순위:
          1. `threshold` 인자가 명시되면 그 값 사용
          2. `image_path` 가 있으면 multi-threshold + OCR/선분 정합도 기반 best 선택 (§69)
          3. 그 외 → Otsu fallback

        priors:
          - `ocr_priors`/`line_priors` 가 제공되면 자체 OCR/line 검출 건너뛰고 그대로 사용.
          - None 이면 fallback 으로 `image_path` 기반 내부 추출.
          - AI 측에서 priors 를 채워주는 흐름(Phase 2)으로 가면 이 path 가 primary.

        반환: `WallExtractionResult` (walls + PostprocessMetadata). 호출자가 metadata
        를 `summary_json` 영속화 / 응답 / 디버깅에 활용.
        """
        from skimage.filters import threshold_otsu

        prob = np.load(str(prob_map_path))

        # A. 좌표계 통일 — AI 가 prob_map 을 작은 해상도(예: 512×512)로 뱉으면
        # OCR bbox(원본 이미지 좌표)와 wall 결과(prob_map 좌표) 가 어긋남.
        # image_path 가 있으면 prob_map 을 원본 이미지 크기로 미리 resize 해서
        # 모든 downstream 처리(mask, skeleton, walls, OCR, dimension match)가 동일
        # 이미지 좌표계에서 동작하도록 보장.
        #
        # ⚠ 정렬 핵심: prob_map 은 반드시 source image dims 로 와야 프론트가 같은
        # scale 로 배경 이미지를 겹쳤을 때 정확. image_path 를 못 읽으면 (download
        # 실패 등) resize 가 스킵돼 prob dims ≠ image dims → 배경 이미지 어긋남.
        _diag_prob_shape = [int(prob.shape[0]), int(prob.shape[1])]
        _diag_image_shape: list[int] | None = None
        _diag_resized = False
        _diag_aligned = False
        if image_path is not None and Path(image_path).exists():
            img_for_dims = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if img_for_dims is not None:
                h_img, w_img = img_for_dims.shape
                _diag_image_shape = [int(h_img), int(w_img)]
                h_prob, w_prob = prob.shape
                if (h_img, w_img) != (h_prob, w_prob):
                    prob = cv2.resize(
                        prob.astype(np.float32), (w_img, h_img),
                        interpolation=cv2.INTER_LINEAR,
                    )
                    _diag_resized = True
                _diag_aligned = True  # prob 이 image 좌표계와 정렬됨 (resize 했거나 이미 동일)
                import logging
                logging.getLogger(__name__).info(
                    "coord align: prob %s → image %s (resized=%s)",
                    _diag_prob_shape, _diag_image_shape, _diag_resized,
                )
            else:
                import logging
                logging.getLogger(__name__).warning(
                    "coord align: image_path 읽기 실패 → prob dims 유지, 배경 정렬 어긋날 수 있음: %s",
                    image_path,
                )
        else:
            import logging
            logging.getLogger(__name__).warning(
                "coord align: image_path 없음 → prob dims 유지, 배경 정렬 어긋날 수 있음",
            )

        # 1. threshold 결정 (+ metadata 동시 빌드, OCR entries 보존)
        # 이 시점의 prob 는 이미 image 좌표계에 정렬되어 있음.
        # priors 가 제공되면 _pick_threshold 가 자체 OCR/line 검출 대신 그걸 사용.
        meta, ocr_entries = self._pick_threshold(
            prob, threshold, image_path,
            ocr_priors=ocr_priors,
            line_priors=line_priors,
        )
        # 좌표계 진단값 기록
        meta.prob_shape = _diag_prob_shape
        meta.image_shape = _diag_image_shape
        meta.coord_resized = _diag_resized
        meta.coord_aligned = _diag_aligned
        if meta.debug_dir is None and debug_dir is not None:
            meta.debug_dir = str(debug_dir)
        if meta.selected_threshold is None:
            otsu_thr = float(threshold_otsu(prob))
            meta.selected_threshold = otsu_thr
            if meta.fallback_reason is None:
                meta.fallback_reason = "explicit_threshold_not_provided"
        thr = meta.selected_threshold
        mask = (prob > thr).astype(np.uint8) * 255

        edges = self._preprocess(mask, debug_dir=debug_dir)
        if edges.sum() == 0:
            return WallExtractionResult(walls=[], postprocess=meta)

        wall_thickness = self.estimate_wall_thickness(edges, detections or [])

        # 2. 확률 가중 스켈레톤 — conf_floor 를 선택된 threshold 에 맞춤 (숨은 0.4 게이트 제거).
        skeleton = self._skeletonize(edges, prob_map=prob, conf_floor=float(thr), debug_dir=debug_dir)

        raw_lines = self._detect_lines(skeleton)
        hv_lines  = self._filter_hv(raw_lines)
        merged    = self._merge_lines(hv_lines, pos_thresh=int(wall_thickness * 3.0))
        snapped   = self._snap_to_hv(merged)
        snapped   = self._filter_hv(snapped, angle_thresh=3.0)
        snapped   = self._snap_intersections(snapped, tol=25.0)
        snapped   = self._snap_endpoints(snapped, tol=20.0)
        filtered  = self._filter_short(snapped, skeleton.shape)
        
        # 3. 신뢰도 필터 — min_conf 를 선택된 threshold 에 맞춤. mask 가 이미 prob>thr 로
        #    1차 필터된 상태라 동일 floor 로 두어 "마스크엔 있는데 여기서 또 떨궈지는" 이중 게이팅 방지.
        filtered  = self._filter_by_confidence(filtered, prob, min_conf=float(thr))

        # 3.5 prior-guided fusion: AI 원본 Hough line(wall_candidate) 중 prob corridor
        # 검증 통과분을 최종 후보에 합침 → U-Net mask 끊김으로 짧게/누락된 벽 복원.
        prior_lines = self._filter_line_priors_by_probability(
            line_priors, prob, float(thr), band_px=4, meta=meta,
        )
        if prior_lines:
            filtered = self._merge_lines(
                filtered + prior_lines, pos_thresh=int(wall_thickness * 3.0)
            )
            filtered = self._snap_to_hv(filtered)
            filtered = self._filter_hv(filtered, angle_thresh=5.0)
            filtered = self._snap_intersections(filtered, tol=25.0)
            filtered = self._snap_endpoints(filtered, tol=20.0)
            import logging
            logging.getLogger(__name__).info(
                "prior line fusion: %d/%d 채택 (저prob %d, 저coverage %d)",
                meta.prior_line_accepted_count, meta.prior_line_candidates_count,
                meta.prior_line_rejected_low_prob_count,
                meta.prior_line_rejected_coverage_count,
            )

        filled = self._fill_opening_gaps(filtered, detections or [])
        filled = self._merge_lines(filled, pos_thresh=int(wall_thickness * 3.0))

        result = []
        for l in filled:
            p1 = np.array([l[0], l[1]])
            p2 = np.array([l[2], l[3]])
            d = np.linalg.norm(p2 - p1)
            if d > 0:
                v = (p2 - p1) / d
                result.append([
                    float((p1 - v * 10)[0]), float((p1 - v * 10)[1]),
                    float((p2 + v * 10)[0]), float((p2 + v * 10)[1]),
                ])

        # 끊긴 끝점 → 가장 가까운 직각 벽으로 연장
        result = self._snap_intersections(result, tol=40.0)
        result = self._snap_endpoints(result, tol=35.0)
        # dangling extend 전에 H/V 강제 정렬 + 비축 라인 제거 (대각선 부작용 차단)
        result = self._snap_to_hv(result)
        result = self._filter_hv(result, angle_thresh=5.0)
        result = self._extend_dangling_endpoints(result, max_extend=200.0, snap_tol=15.0)
        result = self._snap_intersections(result, tol=20.0)

        # 잔여 중복 라인 합치기 (1~2픽셀 차이로 안 합쳐진 것들) + 길이 0 제거
        result = self._merge_lines(result, pos_thresh=10)
        result = [l for l in result if (l[2] - l[0]) ** 2 + (l[3] - l[1]) ** 2 >= 1.0]
        # 이미지 가장자리에 잡힌 캔버스 경계 라인 제거
        result = self._filter_border(result, skeleton.shape, margin_ratio=0.01)

        self._save_debug(skeleton, result, detections or [], debug_dir=debug_dir)

        # 4. Scale 추정 — 우선순위:
        #    (a0) anchored 교차검증: 긴 기준선(체인 전체 span + 벽 외곽 anchor) cluster 합의.
        #         짧은 tick 노이즈에 강함 → 가장 신뢰. (벽 결과 있으면 외곽 anchor 도 사용)
        #    (a) tick-interval: 인접 OCR 치수 중심 거리. anchored 실패 시 fallback.
        #    (b) wall-length fallback: 둘 다 실패하면 OCR ↔ 벽 길이 매칭. (legacy)
        if ocr_entries:
            try:
                from app.services.floorplan.wall_extraction_helpers import dimension_matching

                # (a0) Anchored 교차검증 (긴 기준선 cluster 합의)
                est = dimension_matching.estimate_scale_crossvalidated(
                    ocr_entries, result if result else None,
                )

                # (a) Fallback: tick-interval (인접 페어)
                if est is None:
                    pairs = dimension_matching.find_dimension_interval_pairs(ocr_entries)
                    est = dimension_matching.estimate_scale_from_intervals(pairs)

                # (b) Fallback: wall-length 매칭 (벽 결과 있고 위 모두 실패한 경우만)
                if est is None and result:
                    matches = dimension_matching.match_dimensions_to_walls(
                        ocr_entries, result,
                    )
                    meta.dimension_matches = [m.to_dict() for m in matches]
                    est = dimension_matching.estimate_scale_from_matches(matches)
                elif est is not None:
                    # tick-interval 성공 시에도 wall-length 매칭은 metadata 진단용으로 같이 채움
                    if result:
                        matches = dimension_matching.match_dimensions_to_walls(
                            ocr_entries, result,
                        )
                        meta.dimension_matches = [m.to_dict() for m in matches]

                if est is not None:
                    meta.scale_estimate = est.to_dict()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "dimension matching 실패 (무시하고 진행): %s", exc
                )

        return WallExtractionResult(walls=result, postprocess=meta)

    def _pick_threshold(
        self,
        prob: np.ndarray,
        explicit: float | None,
        image_path: Path | None,
        ocr_priors: list[dict] | None = None,
        line_priors: list[dict] | None = None,
    ) -> tuple[PostprocessMetadata, list]:
        """§69 multi-threshold scoring 으로 best 선택 + 치수 매칭 입력 자료 보존.

        priors:
          - AI 서버가 OCR/line 결과를 같이 내려준 경우 (ocr_priors / line_priors 채워짐)
            → 자체 OCR/line 검출 건너뛰고 그대로 scoring 에 사용.
          - None 이면 fallback 으로 image_path 기반 자체 추출 (legacy).

        반환: `(PostprocessMetadata, ocr_entries)` — ocr_entries 는 후속 dimension
        매칭에 재사용. scoring 비활성이면 빈 리스트.
        """
        from app.services.floorplan.wall_extraction_helpers.threshold_scoring import (
            DEFAULT_THRESHOLDS,
        )
        from app.services.floorplan.wall_extraction_helpers.ocr import OCREntry

        meta = PostprocessMetadata(
            applied=False,
            threshold_candidates=list(DEFAULT_THRESHOLDS),
        )

        if explicit is not None:
            meta.selected_threshold = float(explicit)
            meta.fallback_reason = "explicit_threshold_provided"
            return meta, []

        if image_path is None or not Path(image_path).exists():
            meta.fallback_reason = "source_image_unavailable"
            return meta, []

        try:
            from app.services.floorplan.wall_extraction_helpers import (
                dimension_matching,
                line_detection,
                ocr,
                threshold_scoring,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "wall_extraction_helpers import 실패 → Otsu fallback: %s", exc
            )
            meta.fallback_reason = f"helpers_import_failed: {exc}"
            return meta, []

        # prob_map 과 source image 의 해상도가 다를 수 있음 → image 기준으로 prob_map 리사이즈.
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            meta.fallback_reason = "source_image_read_failed"
            return meta, []
        h_img, w_img = img.shape
        h_prob, w_prob = prob.shape
        if (h_img, w_img) != (h_prob, w_prob):
            prob_resized = cv2.resize(
                prob.astype(np.float32), (w_img, h_img), interpolation=cv2.INTER_LINEAR
            )
        else:
            prob_resized = prob

        # ── OCR entries 결정: priors > 자체 추출 ───────────────────────────
        # None: AI 가 안 줌 → backend fallback
        # []  : AI 가 줬는데 비어있음 → backend fallback 안 함 (디버깅 명확성)
        ocr_entries: list = []
        if ocr_priors is not None:
            # AI 서버에서 받은 priors 사용. dict → OCREntry 재구성.
            # (parsed_value_m / kind 같은 추가 필드도 보존하고 싶으면 OCREntry 확장 필요.
            # 지금은 text/bbox/confidence 만 OCREntry 가 다루므로 그대로 매핑.)
            for p in ocr_priors:
                try:
                    bbox_raw = p.get("bbox", [])
                    bbox = tuple(int(round(float(v))) for v in bbox_raw)
                    if len(bbox) != 4:
                        continue
                    ocr_entries.append(
                        OCREntry(
                            bbox=bbox,  # type: ignore[arg-type]
                            text=str(p.get("text", "")),
                            confidence=float(p.get("confidence") or 0.0),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            meta.ocr_regions_count = len(ocr_entries)
            meta.ocr_priors_source = "ai_service"
        else:
            try:
                ocr_entries = ocr.detect_text_entries(image_path)
                meta.ocr_regions_count = len(ocr_entries)
                meta.ocr_priors_source = "backend_fallback"
                meta.fallback_used = True
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("OCR 추출 실패: %s", exc)
                meta.ocr_priors_source = "none"

        # ocr_penalty(텍스트 위 벽 = 감점) 용 text_mask 는 **신뢰도 높은 OCR 만** 사용.
        # strip/회전으로 늘어난 저신뢰 깨진 글자까지 넣으면 text_mask 가 부풀어
        # ocr_penalty 가 threshold 를 과하게 올리고 강한 외벽까지 깨던 회귀 방지.
        # (scale/span/치수 매칭은 parsed dim 을 쓰므로 이 필터와 무관 — 기능 유지)
        TEXT_MASK_MIN_CONF = 0.5
        text_mask = None
        if ocr_entries:
            try:
                confident_bboxes = [
                    e.bbox for e in ocr_entries if e.confidence >= TEXT_MASK_MIN_CONF
                ]
                text_mask = (
                    ocr.build_text_mask(confident_bboxes, prob_resized.shape, pad=3)
                    if confident_bboxes else None
                )
            except Exception:
                text_mask = None

        # 진단용: 각 OCR entry 의 raw text + bbox + conf + parse 결과를 metadata 에 보관.
        ocr_entries_dump: list[dict] = []
        dim_entries = []
        for e in ocr_entries:
            parsed = dimension_matching.parse_dimension_to_meters(e.text)
            ocr_entries_dump.append({
                "text": e.text,
                "bbox": list(e.bbox),
                "confidence": round(float(e.confidence), 3),
                "parsed_meters": (
                    round(parsed.meters, 4) if parsed is not None else None
                ),
                "parse_confidence": (
                    round(parsed.confidence, 2) if parsed is not None else None
                ),
                "unit_hint": parsed.unit_hint if parsed is not None else None,
            })
            if parsed is not None:
                dim_entries.append(e)
        meta.ocr_entries = ocr_entries_dump
        meta.dimension_entries_count = len(dim_entries)

        # ── Line priors 결정: priors > 자체 추출 ──────────────────────────
        # None: AI 가 안 줌 → backend fallback
        # []  : AI 가 줬는데 비어있음 → backend fallback 안 함
        line_mask = None
        if line_priors is not None:
            import numpy as _np
            # threshold scoring 의 line_alignment 에는 wall_candidate 만 사용한다.
            # AI 가 dimension_line / tick 으로 분류한 선분(치수선)은 벽 점수에서 제외.
            # kind 미지정 선분은 하위호환을 위해 wall_candidate 로 간주.
            wall_segs = [
                p for p in line_priors
                if all(k in p for k in ("x1", "y1", "x2", "y2"))
                and p.get("kind", "wall_candidate") == "wall_candidate"
            ]
            meta.dimension_lines_excluded = int(
                sum(1 for p in line_priors if p.get("kind") == "dimension_line")
            )
            segs_arr = _np.array([
                [int(round(float(p["x1"]))), int(round(float(p["y1"]))),
                 int(round(float(p["x2"]))), int(round(float(p["y2"])))]
                for p in wall_segs
            ], dtype=_np.int32) if wall_segs else _np.empty((0, 4), dtype=_np.int32)
            meta.line_segments_count = int(len(segs_arr))
            meta.line_priors_source = "ai_service"
            if len(segs_arr) > 0:
                try:
                    line_mask = line_detection.build_line_mask(
                        segs_arr, prob_resized.shape, thickness=3,
                    )
                except Exception:
                    line_mask = None
        else:
            try:
                segs = line_detection.detect_line_segments(image_path)
                meta.line_segments_count = int(len(segs))
                line_mask = (
                    line_detection.build_line_mask(segs, prob_resized.shape, thickness=3)
                    if len(segs) > 0 else None
                )
                meta.line_priors_source = "backend_fallback"
                meta.fallback_used = True
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("line detection 실패: %s", exc)
                meta.line_priors_source = "none"

        best_thr, scores = threshold_scoring.pick_best_threshold(
            prob_resized,
            line_mask=line_mask,
            text_mask=text_mask,
            dim_entries=dim_entries,
        )
        meta.applied = True
        meta.selected_threshold = float(best_thr)
        meta.scores = [s.to_dict() for s in scores]
        meta.fallback_reason = None
        return meta, ocr_entries


wall_extractor = WallExtractor()


def run_rule_based_wall_extraction(prob_map_path: Path, detections=None):
    """legacy entry point — walls 좌표 리스트만 반환 (metadata 버림)."""
    return wall_extractor.execute_from_prob_map(prob_map_path, detections=detections).walls