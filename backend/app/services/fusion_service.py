import logging
from typing import Dict, Any, List
from pathlib import Path
import numpy as np
import cv2
import random

from app.schemas.ai_response import MlOutputDTO, MetaDTO, WallSegmentationDTO, DetectionDTO
from app.schemas.scene import SceneSchema, Wall, Opening, Room, Topology

from app.services.geometry_service import GeometryService  
from app.services.wall_extraction import wall_extractor
from app.services.topology_service import TopologyService
from app.services.ai_client import ai_client

logger = logging.getLogger(__name__)

class FusionService:
    def __init__(self):
        self.ai_client = ai_client

    def extract_walls_from_mask(self, mask_path: str, detections: List[DetectionDTO] = None) -> List[Wall]:
        detections = detections or []
        p = Path(mask_path)

        if p.suffix == ".npy":
            try:
                prob = np.load(str(p))
                raw_coords = wall_extractor.execute_from_prob_map(
                    p, threshold=0.5, detections=detections
                )
            except Exception as e:
                logger.error(f"❌ .npy 로드 중 오류: {e}")
                return []
        else:
            img = cv2.imread(mask_path)
            if img is None: return []
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            raw_coords = wall_extractor.execute_from_mask(gray, detections=detections)

        walls = []
        for i, coord in enumerate(raw_coords):
            x1, y1, x2, y2 = coord
            walls.append(Wall(
                id=str(i), x1=float(x1), y1=float(y1),
                x2=float(x2), y2=float(y2), thickness=0.2 # 미터 단위 기본값
            ))
        return walls

    def process_image_to_scene(self, image_bytes: bytes, filename: str, real_width_m: float) -> SceneSchema:
        try:
            ai_results = self.ai_client.fetch_ai_inference(image_bytes, filename)

            unet_res     = ai_results.get("unet", {})
            yolo_res     = ai_results.get("yolo", {})
            unet_output  = unet_res.get("output", {})
            yolo_output  = yolo_res.get("output", {})
            unet_metrics = unet_res.get("metrics", {})

            ml_output = MlOutputDTO(
                meta=MetaDTO(
                    sample_id=unet_res.get("fileId", "temp_id"),
                    image_name=filename,
                    original_width=unet_metrics.get("width", 1000),
                    original_height=unet_metrics.get("height", 1000)
                ),
                wall_segmentation=WallSegmentationDTO(
                    mask_path=unet_output.get("wallProbOverlayPath", ""),
                    prob_map_path=unet_output.get("wallProbNpyPath", "")
                ),
                detections=[
                    DetectionDTO(
                        id=f"det_{i}",
                        class_name=det.get("class_name"),
                        score=float(det.get("confidence", 0.0)),
                        bbox_xyxy=det.get("bbox")
                    )
                    for i, det in enumerate(yolo_output.get("detections", []) or [])
                ]
            )

            return self.run_wi_twin_pipeline(ml_output, real_width_m)

        except Exception as exc:
            logger.error(f"도면 분석 중 오류 발생: {exc}")
            raise

    def run_wi_twin_pipeline(self, ml_output: MlOutputDTO, real_width_m: float) -> SceneSchema:
        geo_service  = GeometryService(
            pixel_width=ml_output.meta.original_width,
            pixel_height=ml_output.meta.original_height,
            real_width_m=real_width_m
        )
        topo_service = TopologyService()
        
        target_path = ml_output.wall_segmentation.prob_map_path or ml_output.wall_segmentation.mask_path
        raw_walls = self.extract_walls_from_mask(target_path, ml_output.detections)

        next_id = len(raw_walls)
        virtual_walls = []
        for det in ml_output.detections:
            if det.class_name in ["door", "window"]:
                bx1, by1, bx2, by2 = det.bbox_xyxy
                is_horizontal = (bx2 - bx1) > (by2 - by1)
                mid = (by1 + by2) / 2 if is_horizontal else (bx1 + bx2) / 2
                virtual_walls.append(Wall(
                    id=str(next_id), 
                    x1=float(bx1) if is_horizontal else float(mid),
                    y1=float(mid) if is_horizontal else float(by1),
                    x2=float(bx2) if is_horizontal else float(mid),
                    y2=float(mid) if is_horizontal else float(by2)
                ))
                next_id += 1

        calibrated_walls = geo_service.calibrate_walls(raw_walls + virtual_walls, ml_output.detections)
        extracted_rooms  = geo_service.extract_rooms(calibrated_walls)
        topology_result  = topo_service.analyze(extracted_rooms, ml_output.detections)

        openings = []
        furniture_objects = []
        for i, det in enumerate(ml_output.detections):
            if det.class_name in ["door", "window"]:
                bx1, by1, bx2, by2 = det.bbox_xyxy
                openings.append(Opening(
                    id=f"opening_{i}", type=det.class_name,
                    x1=float(bx1), y1=float(by1), x2=float(bx2), y2=float(by2)
                ))
            else:
                det.id = f"furniture_{len(furniture_objects)}"
                furniture_objects.append(det)

        return SceneSchema(
       
        scale_ratio=geo_service.scale_ratio,
        
        walls=[w.model_dump() for w in calibrated_walls],
        openings=[o.model_dump() for o in openings],
        rooms=[r.model_dump() for r in extracted_rooms],
        topology=topology_result.model_dump(),
        objects=[obj.model_dump() for obj in furniture_objects]
    )
fusion_service = FusionService()