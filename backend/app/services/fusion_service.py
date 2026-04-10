import logging
from typing import Dict, Any, List

from app.services.geometry_service import GeometryService  
from app.services.wall_extraction import wall_extractor
from app.services.topology_service import TopologyService
from app.schemas.floorplan import Wall
from app.services.ai_client import ai_client
from app.schemas.ai_output import (
    MlOutputDTO, 
    MetaDTO, 
    WallSegmentationDTO, 
    DetectionDTO
)
from app.schemas.floorplan import SceneSchema

logger = logging.getLogger(__name__)

class FusionService:
    def __init__(self):
        self.ai_client = ai_client

    def extract_walls_from_mask(self, mask_path: str) -> List[Wall]:
       
        import cv2
        from pathlib import Path

        img = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"DEBUG: 이미지를 찾을 수 없음 -> {mask_path}")
            return []

       
        raw_coords = wall_extractor.execute_from_mask(img)

        walls = []
        for i, coord in enumerate(raw_coords):
            x1, y1, x2, y2 = coord
            walls.append(Wall(
                id=str(i),
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
                thickness=5.0 
            ))
            
        return walls

    def process_image_to_scene(self, image_bytes: bytes, filename: str, real_width_m: float) -> SceneSchema:
        try:
            ai_results = self.ai_client.fetch_ai_inference(image_bytes, filename)
            
            unet_res = ai_results.get("unet", {})
            yolo_res = ai_results.get("yolo", {})
            
            unet_output = unet_res.get("output", {})
            yolo_output = yolo_res.get("output", {})
            
            unet_metrics = unet_res.get("metrics", {})
            original_width = unet_metrics.get("width", 1000)
            original_height = unet_metrics.get("height", 1000)

            raw_detections = yolo_output.get("detections", [])
            formatted_detections = []
            
            for det in raw_detections:
                formatted_detections.append({
                    "id": str(det.get("class_id")),          
                    "class_name": det.get("class_name"),
                    "score": det.get("confidence"),    
                    "bbox_xyxy": det.get("bbox")        
                })

            ml_output = MlOutputDTO(
                meta=MetaDTO(
                    sample_id=unet_res.get("fileId", "temp_id"),
                    image_name=filename,
                    original_width=original_width, 
                    original_height=original_height
                ),
                wall_segmentation=WallSegmentationDTO(
                    mask_path=unet_output.get("wallProbOverlayPath", ""),
                    prob_map_path=unet_output.get("wallProbNpyPath", "") 
                ),
                detections=formatted_detections  
            )

            return self.run_wi_twin_pipeline(ml_output, real_width_m)

        except Exception as exc:
            logger.error(f"도면 분석 중 오류 발생: {exc}")
            raise exc

    def run_wi_twin_pipeline(self, ml_output: MlOutputDTO, real_width_m: float) -> SceneSchema:
        geo_service = GeometryService(
            pixel_width=ml_output.meta.original_width,
            pixel_height=ml_output.meta.original_height,
            real_width_m=real_width_m
        )
        topo_service = TopologyService()

        mask_path = ml_output.wall_segmentation.mask_path
        raw_walls = self.extract_walls_from_mask(mask_path)

        calibrated_walls = geo_service.calibrate_walls(raw_walls, ml_output.detections)

        extracted_rooms = geo_service.extract_rooms(calibrated_walls)

        topology_result = topo_service.analyze(extracted_rooms, ml_output.detections)

        return SceneSchema(
            walls=calibrated_walls,
            rooms=extracted_rooms,
            detections=ml_output.detections,
            openings=[], 
            scale_ratio=geo_service.scale_ratio,
            topology=topology_result, 
            metadata={
                "image_name": ml_output.meta.image_name,
                "real_width": real_width_m
            }
        )
fusion_service = FusionService()