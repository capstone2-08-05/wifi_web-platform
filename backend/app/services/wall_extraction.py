import cv2
import numpy as np
from pathlib import Path
from typing import List
from app.core.settings import MASK_DIR

class WallExtractor:
    def __init__(self):
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    def extract_centerline(self, dist: np.ndarray) -> np.ndarray:
       
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(dist, kernel)

        centerline = (dist == dilated) & (dist > 0)
        return (centerline * 255).astype(np.uint8)

    def extract_wall_lines(self, mask: np.ndarray) -> List[List[float]]:
      
        lines = cv2.HoughLinesP(
            mask,
            rho=1,
            theta=np.pi / 180,
            threshold=50,     
            minLineLength=60, 
            maxLineGap=30      
        )

        wall_coordinates = []
        debug_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                wall_coordinates.append([float(x1), float(y1), float(x2), float(y2)])
                cv2.line(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 2)

        debug_output_path = MASK_DIR / "debug_vectorization_result.png"
        cv2.imwrite(str(debug_output_path), debug_img)
        
        return wall_coordinates

    def execute_from_mask(self, mask: np.ndarray) -> List[List[float]]:
       
        kernel = np.ones((5, 5), np.uint8)
        merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        dist = cv2.distanceTransform(merged, cv2.DIST_L2, 5)

        skeleton = self.extract_centerline(dist)

        return self.extract_wall_lines(skeleton)

    def run_rule_based_mask(self, image_path: Path) -> np.ndarray:
       
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

        blur = cv2.GaussianBlur(img, (3, 3), 0)
        bw = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY_INV, 31, 5
        )

        kernel = np.ones((5, 5), np.uint8)
        merged = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=3)
        dist = cv2.distanceTransform(merged, cv2.DIST_L2, 5)
        skeleton = self.extract_centerline(dist)

        return skeleton

    def execute(self, image_path: Path) -> List[List[float]]:
       
        skeleton = self.run_rule_based_mask(image_path)
        return self.extract_wall_lines(skeleton)
    
    

wall_extractor = WallExtractor()

def run_rule_based_wall_extraction(image_path: Path):
    return wall_extractor.execute(image_path)