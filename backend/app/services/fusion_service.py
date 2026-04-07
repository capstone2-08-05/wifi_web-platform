from pathlib import Path
from typing import List, Tuple

# 혜승님이 만든 부품들 가져오기
from app.schemas.floorplan import SceneSchema, Wall, Opening
from app.schemas.ai_output import MlOutputDTO  # 성경님 규격 추가
from app.services.geometry_service import GeometryService

class FusionService:
    def __init__(self):
        pass

    def run_wi_twin_pipeline(self, ml_output: MlOutputDTO) -> SceneSchema:
       
        # 1. 메타데이터 추출 
        pixel_width = ml_output.meta.original_width
        pixel_height = ml_output.meta.original_height
        real_width_m = 10.0  # 이건 나중에 사용자가 입력하거나 기준이 필요
        
        # 2. GeometryService 초기화
        geo_service = GeometryService(
            pixel_width=pixel_width, 
            pixel_height=pixel_height, 
            real_width_m=real_width_m
        )

        # 3. 벽 데이터 변환 
        # 일단은 mock 데이터 사용
        pixel_walls = [
            [812, 1240, 1500, 1240],
            [1500, 1240, 1500, 2000]
        ]


        # 실제로 데이터 받으면 밑에 코드 쓰면 됨
        # pixel_walls = self.extractor.extract_from_mask(ml_output.wall_segmentation.mask_path)
        
        converted_walls = geo_service.process_ai_walls(pixel_walls)

        # 4. 벽과 문 병합 로직 
        final_walls, openings = self._refine_walls_with_doors(
            converted_walls, 
            ml_output.detections,
            geo_service
        )

        # 5. 최종 SceneSchema 조립
        result_scene = SceneSchema(
            units="m",
            sourceType="ai_vision_fusion",
            scale_ratio=geo_service.scale_ratio,
            walls=final_walls,
            openings=openings, 
            rooms=[],
            objects=[] 
        )

        print(f"--- 파이프라인 완료: 벽 {len(final_walls)}개, 문 {len(openings)}개 생성 ---")
        return result_scene

    def _refine_walls_with_doors(self, walls: List[Wall], detections, geo_service) -> Tuple[List[Wall], List[Opening]]:
       
        refined_walls = []
        found_openings = []
        
        # YOLO 결과 중 문만 추출
        doors = [d for d in detections if d.class_name == "door"]

        for wall in walls:
            is_door_area = False
            for door in doors:
                
                if self._is_wall_in_door_bbox(wall, door.bbox_xyxy, geo_service):
                    found_openings.append(Opening(
                        id=f"opening_{door.id}",
                        type="door",
                        x1=wall.x1, y1=wall.y1, x2=wall.x2, y2=wall.y2,
                        wall_ref=wall.id
                    ))
                    is_door_area = True
                    break
            
            if not is_door_area:
                refined_walls.append(wall)
        
        return refined_walls, found_openings

    def _is_wall_in_door_bbox(self, wall, bbox, geo_service) -> bool:
        # 미터 좌표를 다시 픽셀로 돌려서 비교 
        px1 = wall.x1 / geo_service.scale_ratio
        py1 = wall.y1 / geo_service.scale_ratio
        
        bx1, by1, bx2, by2 = bbox
        # 벽의 시작점이 문 박스 안에 있으면 겹친다고 판단
        return bx1 <= px1 <= bx2 and by1 <= py1 <= by2

# 인스턴스 생성
fusion_service = FusionService()