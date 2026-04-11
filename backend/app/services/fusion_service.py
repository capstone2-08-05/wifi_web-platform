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

    def extract_walls_from_mask(self, mask_path: str, detections: List[Any] = None) -> List[Wall]:
        import cv2
        from pathlib import Path

        img = cv2.imread(mask_path)
        if img is None: return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        raw_coords = wall_extractor.execute_from_mask(gray, detections=detections)

        if detections:
            for det in detections:
                bbox = getattr(det, 'bbox_xyxy', None) or det.get('bbox_xyxy')
                label = getattr(det, 'class_name', None) or det.get('class_name')
                
                bx1, by1, bx2, by2 = map(int, bbox) 
                cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                cv2.putText(img, label, (bx1, by1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        cv2.imwrite("opening 검출.png", img)

        walls = []
        for i, coord in enumerate(raw_coords):
            x1, y1, x2, y2 = coord
            walls.append(Wall(id=str(i), x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), thickness=5.0))
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
            
            for i, det in enumerate(raw_detections):
                formatted_detections.append(DetectionDTO(
                    id=f"det_{i}",
                    class_name=det.get("class_name"),
                    score=float(det.get("confidence", 0.0)),   
                    bbox_xyxy=det.get("bbox")               
                ))

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

        # [수정 포인트 2] 여기서도 detections를 넘겨줌
        raw_walls = self.extract_walls_from_mask(
            ml_output.wall_segmentation.mask_path, 
            ml_output.detections
        )

        calibrated_walls = geo_service.calibrate_walls(raw_walls, ml_output.detections)
        extracted_rooms = geo_service.extract_rooms(calibrated_walls)
        topology_result = topo_service.analyze(extracted_rooms, ml_output.detections)

        openings = []
        furniture_objects = []
        f_idx = 0

        for i, det in enumerate(ml_output.detections):
            if det.class_name in ["door", "window"]:
                bx1, by1, bx2, by2 = det.bbox_xyxy
                openings.append({
                    "id": f"opening_{i}",
                    "type": det.class_name,
                    "x1": float(bx1), "y1": float(by1),
                    "x2": float(bx2), "y2": float(by2),
                    "wall_id": None
                })
            else:
                det.id = f"furniture_{f_idx}" 
                furniture_objects.append(det)
                f_idx += 1

        return SceneSchema(
            walls=calibrated_walls,
            rooms=extracted_rooms,
            objects=furniture_objects, 
            openings=openings,
            scale_ratio=geo_service.scale_ratio,
            topology=topology_result, 
            metadata={
                "image_name": ml_output.meta.image_name,
                "real_width": real_width_m
            }
        )

fusion_service = FusionService()