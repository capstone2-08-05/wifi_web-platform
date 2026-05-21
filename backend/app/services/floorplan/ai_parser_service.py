import numpy as np
import cv2
from typing import List
# 변경된 경로: ai_output -> ai_response
from app.schemas.ai_response import MlOutputDTO, DetectionDTO

class AIParserService:
    @staticmethod
    def get_adaptive_mask(npy_path: str) -> np.ndarray:
        """
        AI가 생성한 .npy 확률맵을 로드하여 Otsu 이진화를 통해 
        추출하기 쉬운 마스크(0 또는 255)로 변환합니다.
        """
        # 1. 확률맵 로드
        prob_map = np.load(npy_path)
        
        # 2. 0~1 사이의 float를 0~255 uint8로 변환
        prob_uint8 = (prob_map * 255).astype(np.uint8)
        
        # 3. Otsu의 이진화 알고리즘 적용 (가장 적절한 임계값을 자동으로 계산)
        _, mask = cv2.threshold(
            prob_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        
        return mask

    @staticmethod
    def load_yolo_detections(detections: List[DetectionDTO]) -> List[DetectionDTO]:
        """
        YOLO 탐지 결과(DetectionDTO 리스트)를 그대로 반환하거나 
        추후 필터링 로직이 필요할 때 여기서 처리합니다.
        """
        return detections

# 싱글톤 패턴으로 사용하기 쉽게 인스턴스화
ai_parser_service = AIParserService()