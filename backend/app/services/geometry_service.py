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

        def is_hv(w):
            dx, dy = abs(w.x2 - w.x1), abs(w.y2 - w.y1)
            angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
            return angle < 7 or angle > 173 or abs(angle - 90) < 7

        walls = [w for w in walls if is_hv(w)]
        if not walls:
            return []

        lines = [LineString([(w.x1, w.y1), (w.x2, w.y2)]) for w in walls]
        merged = unary_union(lines)

        all_x = [w.x1 for w in walls] + [w.x2 for w in walls]
        all_y = [w.y1 for w in walls] + [w.y2 for w in walls]
        coord_range = max(max(all_x) - min(all_x), max(all_y) - min(all_y))

        snap_tolerance = coord_range * 0.03

        snapped_lines = [snap(line, merged, tolerance=snap_tolerance) for line in lines]
        merged_snapped = unary_union(snapped_lines)

      
        result_geom, dangles, cut_edges, invalid = polygonize_full(merged_snapped)

        polygons = list(result_geom.geoms) if hasattr(result_geom, 'geoms') else []
        dangle_count   = len(list(dangles.geoms))   if hasattr(dangles,   'geoms') else 0
        cut_edge_count = len(list(cut_edges.geoms)) if hasattr(cut_edges, 'geoms') else 0

        print(f" polygonize_full → 폴리곤:{len(polygons)}, dangles(끊긴선):{dangle_count}, cut_edges(미연결):{cut_edge_count}")

        if dangle_count > 3 and len(polygons) < 3:
            snap_tolerance2 = coord_range * 0.05
            snapped_lines2  = [snap(line, merged, tolerance=snap_tolerance2) for line in lines]
            merged_snapped2 = unary_union(snapped_lines2)
            result_geom2, dangles2, cut_edges2, _ = polygonize_full(merged_snapped2)
            polygons2 = list(result_geom2.geoms) if hasattr(result_geom2, 'geoms') else []
            print(f"재시도(tol=5%) → 폴리곤:{len(polygons2)}, dangles:{len(list(dangles2.geoms) if hasattr(dangles2, 'geoms') else [])}")
            if len(polygons2) > len(polygons):
                polygons = polygons2

        rooms = []
        valid_room_count = 0
        for poly in polygons:
            real_area = poly.area * (self.scale_ratio ** 2)
            if real_area < 2.0: 
                continue
            coords = [list(pt) for pt in poly.exterior.coords]
            rooms.append(Room(
                id=f"room_{valid_room_count}",
                points=coords,
                center=[round(poly.centroid.x, 3), round(poly.centroid.y, 3)],
                area=round(real_area, 2)
            ))
            valid_room_count += 1

        logger.info(f"방 추출: 폴리곤 {len(polygons)}개 중 {len(rooms)}개 유효")
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