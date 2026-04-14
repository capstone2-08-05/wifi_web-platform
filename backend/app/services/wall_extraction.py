import cv2
import numpy as np
from pathlib import Path
from typing import List, Any, Tuple
from app.core.settings import MASK_DIR


class WallExtractor:
    def __init__(self):
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 전처리 ─────────────────────────────────────────────────────────
    def _preprocess(self, mask: np.ndarray) -> np.ndarray:
        _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        h, w = binary.shape

        k_size = max(3, int(min(h, w) * 0.01))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
        clean = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size * 2, k_size * 2))
        clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, close_kernel)

        cv2.imwrite(str(MASK_DIR / "debug_edges.png"), clean)
        return clean

    # ── 2. Skeleton ───────────────────────────────────────────────────────
    def _skeletonize(self, edges: np.ndarray, prob_map=None) -> np.ndarray:
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

        # prob_map 있으면 저확률 픽셀 제거
        if prob_map is not None:
            conf_mask = (prob_map > 0.4)
            thinned = ((thinned > 0) & conf_mask).astype(np.uint8) * 255

        cv2.imwrite(str(MASK_DIR / "debug_skeleton.png"), thinned)
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
    def _save_debug(self, skeleton: np.ndarray, lines: List, detections: List[Any] = None):
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

        cv2.imwrite(str(MASK_DIR / "벽 추출.png"), debug)

    # ── 10. 메인 실행 ─────────────────────────────────────────────────────
    def execute_from_mask(self, mask: np.ndarray, detections: List[Any] = None) -> List[List[float]]:
        edges = self._preprocess(mask)
        if edges.sum() == 0:
            return []

        wall_thickness = self.estimate_wall_thickness(edges, detections or [])
        skeleton = self._skeletonize(edges)

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


        self._save_debug(skeleton, extended, detections or [])
        return extended

    def execute_from_unet_image(self, image_path: Path, detections: List[Any] = None) -> List[List[float]]:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return self.execute_from_mask(gray, detections)

    def execute(self, image_path: Path, detections: List[Any] = None) -> List[List[float]]:
        return self.execute_from_unet_image(image_path, detections)

    def execute_from_prob_map(self, prob_map_path: Path, threshold: float = None, detections: List[Any] = None) -> List[List[float]]:
        from skimage.filters import threshold_otsu
        
        prob = np.load(str(prob_map_path))
        
        # 1. Adaptive threshold
        thr = threshold if threshold is not None else threshold_otsu(prob)
        mask = (prob > thr).astype(np.uint8) * 255
        
        edges = self._preprocess(mask)
        if edges.sum() == 0:
            return []

        wall_thickness = self.estimate_wall_thickness(edges, detections or [])
        
        # 2. 확률 가중 스켈레톤
        skeleton = self._skeletonize(edges, prob_map=prob)

        raw_lines = self._detect_lines(skeleton)
        hv_lines  = self._filter_hv(raw_lines)
        merged    = self._merge_lines(hv_lines, pos_thresh=int(wall_thickness * 3.0))
        snapped   = self._snap_to_hv(merged)
        snapped   = self._filter_hv(snapped, angle_thresh=3.0)
        snapped   = self._snap_intersections(snapped, tol=25.0)
        snapped   = self._snap_endpoints(snapped, tol=20.0)
        filtered  = self._filter_short(snapped, skeleton.shape)
        
        # 3. 신뢰도 필터
        filtered  = self._filter_by_confidence(filtered, prob, min_conf=0.6)

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

        self._save_debug(skeleton, result, detections or [])
        return result

wall_extractor = WallExtractor()


# def run_rule_based_wall_extraction(image_path: Path, detections: List[Any] = None):
#     return wall_extractor.execute(image_path, detections)

def run_rule_based_wall_extraction(prob_map_path: Path, detections=None): 
     return wall_extractor.execute_from_prob_map(prob_map_path, detections=detections)