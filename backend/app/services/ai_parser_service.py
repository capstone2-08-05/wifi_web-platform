import numpy as np
import cv2
import json
from typing import List
from app.schemas.ai_output import MlOutputDTO, DetectionDTO

class AIParserService:
    @staticmethod
    def get_adaptive_mask(npy_path: str) -> np.ndarray:
       
        prob_map = np.load(npy_path)
        
        prob_uint8 = (prob_map * 255).astype(np.uint8)
        
        
        _, mask = cv2.threshold(
            prob_uint8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        
        return mask

    @staticmethod
    def load_yolo_detections(detections: List[DetectionDTO]) -> List[DetectionDTO]:
       
        return detections