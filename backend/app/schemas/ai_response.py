from __future__ import annotations
from typing import Literal, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict

class MetaDTO(BaseModel):
    sample_id: str
    image_name: str
    original_width: int = Field(..., gt=0)
    original_height: int = Field(..., gt=0)
    coord_system: Literal["pixel"] = "pixel"
    origin: Literal["top-left"] = "top-left"

class WallSegmentationDTO(BaseModel):
    mask_path: str 
    prob_map_path: Optional[str] = None
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)

class DetectionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    class_name: str = Field(alias="class") 
    score: float = Field(ge=0.0, le=1.0)
    bbox_xyxy: List[float] = Field(..., min_length=4, max_length=4)
    center_xy: Optional[List[float]] = None
    angle_deg: Optional[float] = None     

class QualityDTO(BaseModel):
    wall_mask_quality: Optional[float] = None
    num_detections: int = Field(default=0)
    warnings: List[str] = []

class ArtifactsDTO(BaseModel):
    wall_overlay_path: Optional[str] = None
    detection_overlay_path: Optional[str] = None

class MlOutputDTO(BaseModel):
    meta: MetaDTO
    wall_segmentation: WallSegmentationDTO
    detections: List[DetectionDTO]
    quality: Optional[QualityDTO] = None
    artifacts: Optional[ArtifactsDTO] = None

class RfRunResponseDto(BaseModel):
    rf_run_id: str
    status: Literal["succeeded", "failed"]
    metrics: Optional[dict] = None
    artifacts: Optional[dict] = None
    imageUrl: Optional[str] = None
    detail: Optional[str] = None