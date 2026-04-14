import logging
import numpy as np
from typing import List, Any
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union, snap
from app.schemas.floorplan import Wall, Room

logger = logging.getLogger(__name__)


class GeometryService:
    def __init__(self, pixel_width: int, pixel_height: int, real_width_m: float):
        self.scale_ratio = real_width_m / pixel_width if pixel_width > 0 else 0.1
        self.pixel_height = pixel_height
        self.pixel_width = pixel_width

    def convert_to_meter(self, px_coords: List[float]) -> List[float]:
        return [c * self.scale_ratio for c in px_coords]

    def extract_rooms(self, walls: List[Wall]) -> List[Room]:
        if not walls:
            return []

        # 1. 수직/수평 벽 필터링 (기존 로직 유지)
        def is_hv(w):
            dx, dy = abs(w.x2 - w.x1), abs(w.y2 - w.y1)
            angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
            return angle < 7 or angle > 173 or abs(angle - 90) < 7

        filtered_walls = [w for w in walls if is_hv(w)]
        if not filtered_walls:
            return []

        # 2. 선 병합 및 스냅 (구멍 메우기)
        lines = [LineString([(w.x1, w.y1), (w.x2, w.y2)]) for w in filtered_walls]
        merged = unary_union(lines)
        
        all_x = [w.x1 for w in filtered_walls] + [w.x2 for w in filtered_walls]
        all_y = [w.y1 for w in filtered_walls] + [w.y2 for w in filtered_walls]
        coord_range = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        
        snap_tolerance = coord_range * 0.03
        snapped_lines = [snap(line, merged, tolerance=snap_tolerance) for line in lines]
        merged_snapped = unary_union(snapped_lines)

        # 3. 다각형 생성
        result_geom, dangles, cut_edges, _ = polygonize_full(merged_snapped)
        polygons = list(result_geom.geoms) if hasattr(result_geom, 'geoms') else []

        # 4. 직사각형 변환 및 벽 침범 방지 로직
        rooms = []
        valid_room_count = 0
        
        # 벽 두께의 절반 정도를 안쪽으로 밀어넣기 위한 오프셋 (약 10~15cm)
        # 이미지의 scale_ratio를 사용하여 픽셀 단위로 변환
        shrink_dist = 0.15 / self.scale_ratio 

        for poly in polygons:
            # (1) 안쪽으로 수축: 삐져나온 선이나 벽 두께 침범 제거
            inner_poly = poly.buffer(-shrink_dist)
            if inner_poly.is_empty:
                continue
            
            # (2) 직사각형화: 수축된 모양을 기준으로 반듯한 박스 생성
            rect_poly = inner_poly.envelope
            
            # (3) 면적 계산 (실제 m² 단위)
            real_area = rect_poly.area * (self.scale_ratio ** 2)
            
            # 너무 작거나(노이즈), 너무 큰(집 전체 외곽) 다각형 필터링
            if real_area < 2.0 or real_area > 300.0:
                continue

            # (4) 결과 저장
            coords = [list(pt) for pt in rect_poly.exterior.coords]
            rooms.append(Room(
                id=f"room_{valid_room_count}",
                points=coords,
                center=[round(rect_poly.centroid.x, 3), round(rect_poly.centroid.y, 3)],
                area=round(real_area, 2)
            ))
            valid_room_count += 1

        logger.info(f"방 추출 완료: {len(rooms)}개의 직사각형 방 생성")
        return rooms

    def calibrate_walls(self, walls: List[Wall], detections: List[Any]) -> List[Wall]:
        if not walls:
            return []

        door_px_widths = []
        for d in detections:
            if d.class_name == "door":
                bx1, by1, bx2, by2 = d.bbox_xyxy
                door_px_widths.append(min(abs(bx2 - bx1), abs(by2 - by1)))

        if door_px_widths:
            avg_door_px = sum(door_px_widths) / len(door_px_widths)
            estimated_thickness_m = avg_door_px * self.scale_ratio
            wall_thickness_m = estimated_thickness_m if 0.1 <= estimated_thickness_m <= 0.4 else 0.2
        else:
            wall_thickness_m = 0.2

        for wall in walls:
            wall.thickness = round(wall_thickness_m, 3)

        logger.info(f"벽 두께 보정: {wall_thickness_m:.3f}m")
        return walls