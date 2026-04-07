import cv2
import numpy as np
from pathlib import Path
from typing import List
from app.core.settings import MASK_DIR

class WallExtractor:
    def __init__(self):
        # 마스크 저장 폴더 생성
        MASK_DIR.mkdir(parents=True, exist_ok=True)

    def run_rule_based_mask(self, image_path: Path) -> np.ndarray:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"이미지를 읽을 수 없습니다: {image_path}")

        # 1. 블러로 노이즈 제거
        blur = cv2.GaussianBlur(img, (3, 3), 0)
        
        # 2. 적응형 임계값 처리 (벽 선명하게 따기)
        bw = cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 5
        )

        # 3. 모폴로지 연산 (구멍 메우기 및 잔노이즈 제거)
        kernel_close = np.ones((3, 3), np.uint8)
        closed = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel_close, iterations=2)
        
        kernel_open = np.ones((2, 2), np.uint8)
        cleaned = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel_open, iterations=1)

        # 중간 결과 저장 (디버깅용)
        output_path = MASK_DIR / f"{image_path.stem}_rule_mask.png"
        cv2.imwrite(str(output_path), cleaned)
        
        return cleaned

    def extract_wall_lines(self, mask: np.ndarray) -> List[List[float]]:
        """마스크 이미지에서 벽의 시작/끝 픽셀 좌표 추출 (Hough Transform)"""
        # HoughLinesP: 선분을 확률적으로 검출하는 알고리즘
        # rho=1, theta=np.pi/180, threshold=50, minLineLength=30, maxLineGap=10 (일단 이렇게 두고 파라미터 변경하면서 최적의 값 찾기)
        lines = cv2.HoughLinesP(
            mask, 
            rho=1, 
            theta=np.pi / 180, 
            threshold=40, 
            minLineLength=25, 
            maxLineGap=15
        )

        wall_coordinates = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                # 정의한 AIAnalysisRequest 형식에 맞게 리스트로 저장
                wall_coordinates.append([float(x1), float(y1), float(x2), float(y2)])

        return wall_coordinates

    def execute(self, image_path: Path) -> List[List[float]]:
        mask = self.run_rule_based_mask(image_path)
        pixel_walls = self.extract_wall_lines(mask)
        return pixel_walls

# 외부에서 편하게 쓸 수 있게 인스턴스 생성
wall_extractor = WallExtractor()