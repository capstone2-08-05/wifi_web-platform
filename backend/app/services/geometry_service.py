import logging
from typing import List, Any, Tuple
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import polygonize
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

        lines = []
       
        snap_size = 5.0 
        
        for w in walls:
            nx1, ny1 = round(w.x1 / snap_size) * snap_size, round(w.y1 / snap_size) * snap_size
            nx2, ny2 = round(w.x2 / snap_size) * snap_size, round(w.y2 / snap_size) * snap_size
            
            if nx1 == nx2 and ny1 == ny2:
                continue
            lines.append(LineString([(nx1, ny1), (nx2, ny2)]))
        
    
        mls = MultiLineString(lines)
        
        polygons = list(polygonize(mls))
        
        rooms = []
        valid_room_count = 0
        
        for poly in polygons:
            real_area = poly.area * (self.scale_ratio ** 2)
            
          
            if real_area < 5.0:
                continue
            
            coords = [list(pt) for pt in poly.exterior.coords]
            
            rooms.append(Room(
                id=f"room_{valid_room_count}",
                points=coords,
                center=[round(poly.centroid.x, 3), round(poly.centroid.y, 3)],
                area=round(real_area, 2)
            ))
            valid_room_count += 1
            
        logger.info(f"최종 추출된 유효 방 개수: {len(rooms)}")
        return rooms

    def calibrate_walls(self, walls: List[Wall], detections: List[Any]) -> List[Wall]:
      
        if not walls:
            return []

        door_widths = []
        for d in detections:
            if d.class_name == "door":
                bx1, by1, bx2, by2 = d.bbox_xyxy
                w_px = min(abs(bx2 - bx1), abs(by2 - by1))
                door_widths.append(w_px * self.scale_ratio) 

        avg_thickness = sum(door_widths) / len(door_widths) if door_widths else 0.2
        
        for wall in walls:
            wall.thickness = round(avg_thickness, 3)
                
        return walls