from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List
from app.schemas.scene import SceneSchema 

class ConfigDTO(BaseModel):
    frequency_ghz: float = 2.4  # 기본값 2.4GHz
    tx_power_dbm: float = 30.0
    reflection_order: int = 2

class AntennaDTO(BaseModel):
    tx_id: str = "router_1"
    position_m: List[float] = [1.0, 1.0, 1.0] # [x, y, z] 좌표

# 전체를 묶는 DTO
class SionnaInputDTO(BaseModel):
    config: ConfigDTO
    antenna: AntennaDTO
    scene: SceneSchema # /space/analyze 결과가 들어갈 곳