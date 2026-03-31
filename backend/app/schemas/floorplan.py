from pydantic import BaseModel
from typing import List, Dict, Any

# AI가 혜승님께 줄 픽셀 데이터
class AIAnalysisRequest(BaseModel):
    image_width: int
    image_height: int
    walls: List[List[float]]
    detections: List[Dict[str, Any]]

# 혜승님이 가공해서 내보낼 미터 데이터
class ProcessedWall(BaseModel):
    id: int
    start_pos: List[float]
    end_pos: List[float]
    material: str = "concrete"

class SceneGraphResponse(BaseModel):
    scale_ratio: float
    walls: List[ProcessedWall]