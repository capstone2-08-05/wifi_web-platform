import cv2
import numpy as np
from pathlib import Path
from typing import List
from app.schemas.floorplan import Wall
from app.services.wall_extraction import wall_extractor 

class GeometryService:
    def __init__(self, pixel_width: int, pixel_height: int, real_width_m: float):
        self.scale_ratio = real_width_m / pixel_width
        self.pixel_height = pixel_height

    def convert_pixel_to_meter(self, px: float, py: float):
        mx = px * self.scale_ratio
        my = py * self.scale_ratio 
        return round(mx, 3), round(my, 3)

    def process_image_to_walls(self, image_path: Path) -> List[Wall]:
        
        # 1. 픽셀 좌표 리스트 추출 ([[x1, y1, x2, y2], ...])
        pixel_walls = wall_extractor.execute(image_path)
        
        processed = []
        
        # 2. 추출된 픽셀 데이터를 하나씩 돌면서 Wall 객체로 변환
        for i, coords in enumerate(pixel_walls):
            mx1, my1 = self.convert_pixel_to_meter(coords[0], coords[1])
            mx2, my2 = self.convert_pixel_to_meter(coords[2], coords[3])
            
            wall_obj = Wall(
                id=f"wall_{i}",
                x1=mx1,
                y1=my1,
                x2=mx2,
                y2=my2,
                thickness=0.2, 
                height=2.5,    
                role="inner"   
            )
            processed.append(wall_obj)
            
        return processed

