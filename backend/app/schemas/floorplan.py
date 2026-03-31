from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# 1. AI로부터 받는 원본 데이터 (입력)
class AIAnalysisRequest(BaseModel):
    image_width: int
    image_height: int
    walls: List[List[float]]  # [[x1, y1, x2, y2], ...] 형태
    detections: List[Dict[str, Any]]

# 2. JSON 스키마 규격에 맞춘 벽 데이터 (출력용 개별 항목)
class Wall(BaseModel):
    id: str
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float = 0.2   # 기본값 20cm (필요시 수정)
    height: float = 2.5      # 기본값 2.5m (필요시 수정)
    role: str = "inner"      # "inner" 또는 "outer"
    material: str = "concrete"

# 3. 최종적으로 내보낼 전체 데이터 구조
class SceneGraphResponse(BaseModel):
    units: str = "m"
    sourceType: str = "ai_vision"
    scale_ratio: float       # 1픽셀당 몇 미터인지 (계산된 값)
    walls: List[Wall]
    openings: List[Any] = [] # 문, 창문 등 (추후 확장용)
    rooms: List[Any] = []    # 방 구역 정보
    objects: List[Any] = []  # 가구 등 배치 오브젝트