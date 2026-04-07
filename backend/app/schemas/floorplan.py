from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# 1. AI로부터 받는 원본 데이터 (입력)
class AIAnalysisRequest(BaseModel):
    image_width: int
    image_height: int
    walls: List[List[float]]  # [[x1, y1, x2, y2], ...] 형태
    detections: List[Dict[str, Any]]

# 2. 개별 벽 데이터 (출력용)
class Wall(BaseModel):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float = 0.2
    height: float = 2.5
    role: str = "inner"
    material: str = "concrete"

# 문, 창문 등 개구부 데이터 (출력용)
class Opening(BaseModel):
    id: str
    type: str  
    x1: float
    y1: float
    x2: float
    y2: float
    wall_ref: Optional[str] = None  # 어떤 벽 자리에 들어갔는지 참조

# 3. 최종적으로 내보낼 전체 데이터 구조 (Scene Graph)
class SceneSchema(BaseModel):

    scene_version: str = "1.0.0"
    units: str = "m"
    sourceType: str = "ai_vision"
    scale_ratio: float       
    walls: List[Wall]
    openings: List[Opening]  
    rooms: List[Any] = []    
    objects: List[Any] = []