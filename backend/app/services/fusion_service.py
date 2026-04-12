import logging
from typing import Dict, Any, List
from pathlib import Path
import numpy as np

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
        import numpy as np
        from pathlib import Path

        detections = detections or []

        p = Path(mask_path)

        print("\n" + "="*50)
        print(f"🔍 [WALL EXTRACTION DEBUG]")
        print(f"   > 대상 파일: {mask_path}")
        print(f"   > 존재 여부: {p.exists()}")
        print(f"   > 파일 확장자: {p.suffix}")

        if p.suffix == ".npy":
            print(" 결과: .npy (확률맵) 기반으로 정밀 추출을 시작합니다.")
            logger.info(f"[Data Source] UNet 확률맵(.npy) 사용: {p.name}")
            try:
                prob = np.load(str(p))
                img  = cv2.cvtColor((prob * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
                raw_coords = wall_extractor.execute_from_prob_map(
                    p, threshold=0.5, detections=detections
                )
            except Exception as e:
                print(f"❌ 에러 발생: {e}")
                logger.error(f"❌ .npy 로드 중 오류: {e}")
                return []
        else:
            print("⚠️ 결과: .npy가 아니므로 일반 이미지를 사용합니다.")
            logger.warning(f"[Data Source] 일반 이미지 사용: {p.name}")
            img = cv2.imread(mask_path)
            if img is None:
                print(f"❌ 에러: 이미지를 읽을 수 없음 ({mask_path})")
                return []
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            raw_coords = wall_extractor.execute_from_mask(gray, detections=detections)
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        print(f" 추출된 벽 선분 개수: {len(raw_coords)}")
        print("="*50 + "\n")

        if detections:
            for det in detections:
                bbox  = getattr(det, 'bbox_xyxy', None) or (det.get('bbox_xyxy') if isinstance(det, dict) else None)
                label = getattr(det, 'class_name', "obj") or (det.get('class_name') if isinstance(det, dict) else "obj")
                if bbox:
                    bx1, by1, bx2, by2 = map(int, bbox)
                    cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                    cv2.putText(img, label, (bx1, by1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.imwrite("오프닝 추출.png", img)

        walls = []
        for i, coord in enumerate(raw_coords):
            x1, y1, x2, y2 = coord
            walls.append(Wall(
                id=str(i), x1=float(x1), y1=float(y1),
                x2=float(x2), y2=float(y2), thickness=5.0
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

            original_width  = unet_metrics.get("width", 1000)
            original_height = unet_metrics.get("height", 1000)

            raw_detections = yolo_output.get("detections", []) or []  # ← None 방어
            formatted_detections = [
                DetectionDTO(
                    id=f"det_{i}",
                    class_name=det.get("class_name"),
                    score=float(det.get("confidence", 0.0)),
                    bbox_xyxy=det.get("bbox")
                )
                for i, det in enumerate(raw_detections)
            ]

            prob_map_path = unet_output.get("wallProbNpyPath", "")
            mask_path     = unet_output.get("wallProbOverlayPath", "")

            ml_output = MlOutputDTO(
                meta=MetaDTO(
                    sample_id=unet_res.get("fileId", "temp_id"),
                    image_name=filename,
                    original_width=original_width,
                    original_height=original_height
                ),
                wall_segmentation=WallSegmentationDTO(
                    mask_path=mask_path,
                    prob_map_path=prob_map_path
                ),
                detections=formatted_detections
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

        detections = ml_output.detections or []

        target_path = (
            ml_output.wall_segmentation.prob_map_path
            if ml_output.wall_segmentation.prob_map_path
            else ml_output.wall_segmentation.mask_path
        )

        raw_walls = self.extract_walls_from_mask(target_path, detections)

        virtual_walls = []
        for det in detections:
            if det.class_name not in ["door", "window"]:
                continue
            bx1, by1, bx2, by2 = det.bbox_xyxy
            is_horizontal = (bx2 - bx1) > (by2 - by1)
            if is_horizontal:
                mid_y = (by1 + by2) / 2
                virtual_walls.append(Wall(
                    id=f"v_wall_{det.id}", x1=float(bx1), y1=float(mid_y),
                    x2=float(bx2), y2=float(mid_y), thickness=5.0
                ))
            else:
                mid_x = (bx1 + bx2) / 2
                virtual_walls.append(Wall(
                    id=f"v_wall_{det.id}", x1=float(mid_x), y1=float(by1),
                    x2=float(mid_x), y2=float(by2), thickness=5.0
                ))

        walls_for_room  = raw_walls + virtual_walls
        calibrated_walls = geo_service.calibrate_walls(walls_for_room, detections)
        extracted_rooms  = geo_service.extract_rooms(calibrated_walls)

        import cv2, random

        if Path(target_path).suffix == ".npy":
            prob_data = np.load(str(target_path))
            h, w = prob_data.shape[:2]
        else:
            h, w = ml_output.meta.original_height, ml_output.meta.original_width

        room_debug = np.zeros((h, w, 3), dtype=np.uint8)

        for room in extracted_rooms:
            color    = [random.randint(50, 200) for _ in range(3)]
            pts_attr = getattr(room, 'outline_pts',
                       getattr(room, 'points',
                       getattr(room, 'vertices', None)))
            if pts_attr is not None:
                pts = np.array(pts_attr, dtype=np.int32)
                if len(pts) > 0:
                    pts[:, 0] = np.clip(pts[:, 0], 0, w - 1)
                    pts[:, 1] = np.clip(pts[:, 1], 0, h - 1)
                    cv2.fillPoly(room_debug, [pts], color)
                    txt_x = int(np.clip(np.mean(pts[:, 0]), 10, w - 10))
                    txt_y = int(np.clip(np.mean(pts[:, 1]), 10, h - 10))
                    cv2.putText(room_debug, f"Room_{room.id}", (txt_x, txt_y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        for wall in calibrated_walls:
            cv2.line(room_debug,
                     (int(np.clip(wall.x1, 0, w-1)), int(np.clip(wall.y1, 0, h-1))),
                     (int(np.clip(wall.x2, 0, w-1)), int(np.clip(wall.y2, 0, h-1))),
                     (255, 255, 255), 1)

        cv2.imwrite("방 추출.png", room_debug)

        topology_result   = topo_service.analyze(extracted_rooms, detections)
        openings          = []
        furniture_objects = []

        for i, det in enumerate(detections):
            if det.class_name in ["door", "window"]:
                bx1, by1, bx2, by2 = det.bbox_xyxy
                openings.append({
                    "id": f"opening_{i}", "type": det.class_name,
                    "x1": float(bx1), "y1": float(by1),
                    "x2": float(bx2), "y2": float(by2),
                    "wall_id": None
                })
            else:
                det.id = f"furniture_{len(furniture_objects)}"
                furniture_objects.append(det)

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