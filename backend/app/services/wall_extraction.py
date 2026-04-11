import cv2
import numpy as np
from pathlib import Path
from typing import List, Any
from app.core.settings import MASK_DIR


class WallExtractor:
    def __init__(self):
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    def extract_centerline(self, dist: np.ndarray) -> np.ndarray:
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(dist, kernel)
        centerline = (dist == dilated) & (dist > 0)
        return (centerline * 255).astype(np.uint8)

    def estimate_wall_thickness(self, mask: np.ndarray, detections: List[Any]) -> float:
        thickness_samples = []
        if detections:
            for det in detections:
                if det.class_name in ["door", "window"]:
                    x1, y1, x2, y2 = map(int, det.bbox_xyxy)
                    roi = mask[y1:y2, x1:x2]
                    if roi.size == 0:
                        continue
                    dist = cv2.distanceTransform((roi > 0).astype(np.uint8), cv2.DIST_L2, 5)
                    if dist.max() > 0:
                        thickness_samples.append(dist.max())

        if len(thickness_samples) == 0:
            dist_full = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
            return max(3, np.percentile(dist_full, 90))
        return np.median(thickness_samples)

    def _is_hv_line(self, x1: int, y1: int, x2: int, y2: int, angle_thresh: float = 15.0) -> bool:
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180
        is_h = angle < angle_thresh or angle > (180 - angle_thresh)
        is_v = abs(angle - 90) < angle_thresh
        return is_h or is_v
    
    

    def _merge_similar_lines(self, lines: List, pos_thresh: int = 25, angle_thresh: float = 10.0) -> List:
        if not lines:
            return []
        used = [False] * len(lines)
        result = []
        for i, (x1, y1, x2, y2) in enumerate(lines):
            if used[i]:
                continue
            group = [(x1, y1, x2, y2)]
            a1 = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
            for j, (x3, y3, x4, y4) in enumerate(lines):
                if i == j or used[j]:
                    continue
                a2 = np.degrees(np.arctan2(y4 - y3, x4 - x3)) % 180
                if min(abs(a1 - a2), 180 - abs(a1 - a2)) > angle_thresh:
                    continue
                if a1 < 45 or a1 > 135:  # 수평선: y 거리
                    if abs((y1 + y2) / 2 - (y3 + y4) / 2) < pos_thresh:
                        group.append((x3, y3, x4, y4))
                        used[j] = True
                else:  # 수직선: x 거리
                    if abs((x1 + x2) / 2 - (x3 + x4) / 2) < pos_thresh:
                        group.append((x3, y3, x4, y4))
                        used[j] = True
            best = max(group, key=lambda l: np.hypot(l[2] - l[0], l[3] - l[1]))
            result.append(best)
            used[i] = True
        return result

    def extract_wall_lines(self, mask: np.ndarray, wall_thickness: float) -> List[List[float]]:
        dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        skeleton = self.extract_centerline(dist)

        h, w = skeleton.shape
        lines = cv2.HoughLinesP(
            skeleton,
            rho=1,
            theta=np.pi / 180,
            threshold=20,                 
            minLineLength=int(min(h, w) * 0.1), 
            maxLineGap=20,                 
        )

        debug_img = cv2.cvtColor(skeleton, cv2.COLOR_GRAY2BGR)

        if lines is None:
            cv2.imwrite(str(MASK_DIR / "벽추출_최종.png"), debug_img)
            return []

        raw = [l[0].tolist() for l in lines]

        hv_lines = [(x1, y1, x2, y2) for x1, y1, x2, y2 in raw if self._is_hv_line(x1, y1, x2, y2)]

        merged = self._merge_similar_lines(hv_lines)

        wall_coordinates = []
        for x1, y1, x2, y2 in merged:
            wall_coordinates.append([float(x1), float(y1), float(x2), float(y2)])
            cv2.line(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 2)

        cv2.imwrite(str(MASK_DIR / "벽추출_최종.png"), debug_img)
        return wall_coordinates

    def execute_from_mask(self, mask: np.ndarray, detections: List[Any] = None) -> List[List[float]]:
        _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
        filtered = np.zeros_like(binary)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] > 1000:
                filtered[labels == i] = 255

        if filtered.sum() == 0:
            return []

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        eroded = cv2.erode(filtered, kernel, iterations=2)
        edges = cv2.subtract(filtered, eroded)

        k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1))
        k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k_h)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k_v)

        cv2.imwrite(str(MASK_DIR / "final_binary_mask_debug.png"), edges)

        wall_thickness = self.estimate_wall_thickness(edges, detections)
        return self.extract_wall_lines(edges, wall_thickness)

    def execute_from_unet_image(self, image_path: Path, detections: List[Any] = None) -> List[List[float]]:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return self.execute_from_mask(gray, detections)

    def execute(self, image_path: Path, detections: List[Any] = None) -> List[List[float]]:
        return self.execute_from_unet_image(image_path, detections)


wall_extractor = WallExtractor()


def run_rule_based_wall_extraction(image_path: Path, detections: List[Any] = None):
    return wall_extractor.execute(image_path, detections)