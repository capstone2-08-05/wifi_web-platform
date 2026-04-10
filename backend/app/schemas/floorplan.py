from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# 1. AI로부터 받는 원본 데이터 
class AIAnalysisRequest(BaseModel):
    image_width: int
    image_height: int
    walls: List[List[float]]
    detections: List[Dict[str, Any]]

# 2. 개별 벽 데이터 
class Wall(BaseModel):
    id: str
    x1: float; y1: float; x2: float; y2: float
    thickness: float = 0.2
    height: float = 2.5
    role: str = "inner"
    material: str = "concrete"

# 개구부 데이터
class Opening(BaseModel):
    id: str
    type: str  
    x1: float; y1: float; x2: float; y2: float
    wall_ref: Optional[str] = None


# 3. 방 영역 데이터
class Room(BaseModel):
    id: str
    points: List[List[float]]  
    center: List[float]        
    area: float              

# 4. 공간 위상 관계 (Topology)
class Topology(BaseModel):
    adjacencies: List[List[str]] 
    connectivity: List[List[str]]  

# 5. 최종 SceneSchema 
class SceneSchema(BaseModel):
    scene_version: str = "1.0.0"
    units: str = "m"
    sourceType: str = "ai_vision"
    scale_ratio: float       
    walls: List[Wall]
    openings: List[Opening]  
    rooms: List[Room] = []          
    topology: Optional[Topology] = None 
    objects: List[Any] = []