import cv2
import numpy as np
from pathlib import Path
from typing import List
from app.core.settings import MASK_DIR


class WallExtractor:
    def __init__(self):
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    # 🔥 중심선 추출 (Distance Transform + Local Maxima)
    def extract_centerline(self, dist: np.ndarray) -> np.ndarray:
        kernel = np.ones((3, 3), np.uint8)

        # 주변보다 값이 큰 지점 = ridge (중심선)
        dilated = cv2.dilate(dist, kernel)

        centerline = (dist == dilated) & (dist > 0)
        centerline = (centerline * 255).astype(np.uint8)

        return centerline

    def run_rule_based_mask(self, image_path: Path) -> np.ndarray:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

        # 1. 노이즈 제거 + 이진화
        blur = cv2.GaussianBlur(img, (3, 3), 0)
        bw = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            5,
        )

        # 2. 벽 덩어리 합치기 (edge → 하나의 blob으로)
        kernel = np.ones((5, 5), np.uint8)
        merged = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=3)

        # 3. Distance Transform
        dist = cv2.distanceTransform(merged, cv2.DIST_L2, 5)

        # 4. 중심선 추출 (🔥 핵심)
        skeleton = self.extract_centerline(dist)

        # 저장
        output_path = MASK_DIR / f"{image_path.stem}_skeleton_mask.png"
        cv2.imwrite(str(output_path), skeleton)

        return skeleton

    def extract_wall_lines(self, mask: np.ndarray) -> List[List[float]]:
        lines = cv2.HoughLinesP(
            mask,
            rho=1,
            theta=np.pi / 180,
            threshold=50,
            minLineLength=80,
            maxLineGap=30,
        )

        debug_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        wall_coordinates = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]

                wall_coordinates.append(
                    [float(x1), float(y1), float(x2), float(y2)]
                )

                cv2.line(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 2)

        debug_output_path = MASK_DIR / "debug_vectorization_result.png"
        cv2.imwrite(str(debug_output_path), debug_img)

        print(f"🖼️  추출 결과 시각화 완료: {debug_output_path}")

        return wall_coordinates

    def execute(self, image_path: Path) -> List[List[float]]:
        skeleton = self.run_rule_based_mask(image_path)
        pixel_walls = self.extract_wall_lines(skeleton)
        return pixel_walls


wall_extractor = WallExtractor()