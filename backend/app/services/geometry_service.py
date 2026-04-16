import logging
import numpy as np
from typing import List, Any
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union, snap

# 변경된 경로: floorplan -> scene
from app.schemas.scene import Wall, Room

logger = logging.getLogger(__name__)

class GeometryService:
    def __init__(self, pixel_width: int, pixel_height: int, real_width_m: float):
        # 픽셀 당 미터 비율 계산
        self.scale_ratio = real_width_m / pixel_width if pixel_width > 0 else 0.1
        self.pixel_height = pixel_height
        self.pixel_width = pixel_width

    def convert_to_meter(self, px_coords: List[float]) -> List[float]:
        """픽셀 좌표 리스트를 미터 단위로 변환합니다."""
        return [c * self.scale_ratio for c in px_coords]

    def extract_rooms(self, walls: List[Wall]) -> List[Room]:
        """
        추출된 벽 정보를 바탕으로 닫힌 공간(Room)을 찾고, 
        이를 직사각형 형태로 보정하여 반환합니다.
        """
        if not walls:
            return []

        # 1. 수직/수평 벽 필터링 (기울어진 노이즈 제거)
        def is_hv(w):
            dx, dy = abs(w.x2 - w.x1), abs(w.y2 - w.y1)
            angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
            return angle < 7 or angle > 173 or abs(angle - 90) < 7

        filtered_walls = [w for w in walls if is_hv(w)]
        if not filtered_walls:
            return []

        # 2. 선 병합 및 스냅 (끊어진 벽 연결)
        lines = [LineString([(w.x1, w.y1), (w.x2, w.y2)]) for w in filtered_walls]
        merged = unary_union(lines)
        
        all_x = [w.x1 for w in filtered_walls] + [w.x2 for w in filtered_walls]
        all_y = [w.y1 for w in filtered_walls] + [w.y2 for w in filtered_walls]
        coord_range = max(max(all_x) - min(all_x), max(all_y) - min(all_y))
        
        # 전체 범위의 3% 이내 오차는 하나로 붙임
        snap_tolerance = coord_range * 0.03
        snapped_lines = [snap(line, merged, tolerance=snap_tolerance) for line in lines]
        merged_snapped = unary_union(snapped_lines)

        # 3. 다각형 생성 (Polygonize)
        result_geom, dangles, cut_edges, _ = polygonize_full(merged_snapped)
        polygons = list(result_geom.geoms) if hasattr(result_geom, 'geoms') else []

        # 4. 방 데이터 생성 및 정규화
        rooms = []
        valid_room_count = 0
        
        # 벽 두께(약 15cm)만큼 안쪽으로 수축하여 실제 가용 면적 계산
        shrink_dist = 0.15 / self.scale_ratio 

        for poly in polygons:
            # (1) 안쪽으로 수축
            inner_poly = poly.buffer(-shrink_dist)
            if inner_poly.is_empty:
                continue
            
            # (2) 직사각형화 (Envelope)
            rect_poly = inner_poly.envelope
            
            # (3) 면적 계산 (m²)
            real_area = rect_poly.area * (self.scale_ratio ** 2)
            
            # 너무 작거나(노이즈) 너무 큰(외곽선) 공간 필터링
            if real_area < 2.0 or real_area > 300.0:
                continue

            # (4) Room 객체 생성
            coords = [list(pt) for pt in rect_poly.exterior.coords]
            rooms.append(Room(
                id=f"room_{valid_room_count}",
                points=coords,
                center=[round(rect_poly.centroid.x, 3), round(rect_poly.centroid.y, 3)],
                area=round(real_area, 2)
            ))
            valid_room_count += 1

        logger.info(f"방 추출 완료: {len(rooms)}개의 방 생성")
        return rooms

    def calibrate_walls(self, walls: List[Wall], detections: List[Any]) -> List[Wall]:
        """
        탐지된 문의 크기를 기준으로 이미지의 실제 벽 두께를 추정하고 보정합니다.
        """
        if not walls:
            return []

        # 문의 폭을 통해 벽 두께 추정
        door_px_widths = []
        for d in detections:
            # DetectionDTO 구조에 따라 접근 (class_name 또는 class)
            label = getattr(d, 'class_name', getattr(d, 'class', None))
            if label == "door":
                bx1, by1, bx2, by2 = d.bbox_xyxy
                door_px_widths.append(min(abs(bx2 - bx1), abs(by2 - by1)))

        if door_px_widths:
            avg_door_px = sum(door_px_widths) / len(door_px_widths)
            estimated_thickness_m = avg_door_px * self.scale_ratio
            # 상식적인 범위(10cm~40cm)를 벗어나면 20cm로 고정
            wall_thickness_m = estimated_thickness_m if 0.1 <= estimated_thickness_m <= 0.4 else 0.2
        else:
            wall_thickness_m = 0.2

        # 모든 벽의 두께 업데이트
        for wall in walls:
            wall.thickness = round(wall_thickness_m, 3)

        logger.info(f"벽 두께 보정 완료: {wall_thickness_m:.3f}m")
        return walls