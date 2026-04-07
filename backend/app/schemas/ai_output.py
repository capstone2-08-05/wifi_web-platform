from __future__ import annotations
from typing import Literal, List, Optional
from pydantic import BaseModel, Field, ConfigDict

# 1. 메타데이터: 이미지의 기본 정보 (좌표 변환의 기준)
class MetaDTO(BaseModel):
    sample_id: str
    image_name: str
    original_width: int = Field(..., gt=0, description="이미지 가로 픽셀 수")
    original_height: int = Field(..., gt=0, description="이미지 세로 픽셀 수")
    coord_system: Literal["pixel"] = "pixel"
    origin: Literal["top-left"] = "top-left"

# 2. U-Net 결과: 벽 분할 마스크 경로
class WallSegmentationDTO(BaseModel):
    mask_path: str 
    prob_map_path: Optional[str] = None
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)

# 3. YOLO 결과: 탐지된 객체 정보
class DetectionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    class_name: str = Field(alias="class") 
    score: float = Field(ge=0.0, le=1.0)    # 신뢰도 (0~1)
    bbox_xyxy: List[float] = Field(..., min_length=4, max_length=4) # [x1, y1, x2, y2]
    center_xy: Optional[List[float]] = None
    angle_deg: Optional[float] = None     

# 4. 품질 및 시각화 데이터
class QualityDTO(BaseModel):
    wall_mask_quality: Optional[float] = None
    num_detections: int = Field(default=0)
    warnings: List[str] = []

class ArtifactsDTO(BaseModel):
    wall_overlay_path: Optional[str] = None
    detection_overlay_path: Optional[str] = None

# 5. 최종적으로 ai가 백으로 주는 데이터 구조
class MlOutputDTO(BaseModel):
    meta: MetaDTO
    wall_segmentation: WallSegmentationDTO
    detections: List[DetectionDTO]
    quality: Optional[QualityDTO] = None
    artifacts: Optional[ArtifactsDTO] = None