from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class Wall(BaseModel):
    id: str
    x1: float; y1: float; x2: float; y2: float
    thickness: float = 0.2
    height: float = 2.5
    role: str = "inner"
    material: str = "concrete"

class Opening(BaseModel):
    id: str
    type: str  
    x1: float; y1: float; x2: float; y2: float
    wall_ref: Optional[str] = None

class Room(BaseModel):
    id: str
    points: List[List[float]]  
    center: List[float]        
    area: float              

class Topology(BaseModel):
    adjacencies: List[List[str]] 
    connectivity: List[List[str]]  

class SimConfigDTO(BaseModel):
    frequency_ghz: float = 28.0
    tx_power_dbm: float = 30.0
    reflection_order: int = 2

class AntennaDTO(BaseModel):
    tx_id: str = "router_1"
    position_m: List[float] = Field(..., description="[x, y, z] 실제 미터 좌표")


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


class SionnaInputDTO(BaseModel):
   
    config: SimConfigDTO
    antenna: AntennaDTO
    scene: SceneSchema