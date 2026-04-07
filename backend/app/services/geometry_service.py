from app.schemas.floorplan import Wall 

class GeometryService:
    def __init__(self, pixel_width: int, pixel_height: int, real_width_m: float):
        # 1픽셀당 몇 미터인지 (Scale Ratio) 계산
        self.scale_ratio = real_width_m / pixel_width
        self.pixel_height = pixel_height

    def convert_pixel_to_meter(self, px: float, py: float):
        # 픽셀 좌표를 실제 미터 단위로 변환
        mx = px * self.scale_ratio
        my = py * self.scale_ratio 
        return round(mx, 3), round(my, 3)

    def process_ai_walls(self, wall_data: list) -> list[Wall]:
        processed = []
        for i, coords in enumerate(wall_data):
            mx1, my1 = self.convert_pixel_to_meter(coords[0], coords[1])
            mx2, my2 = self.convert_pixel_to_meter(coords[2], coords[3])
            
            wall_obj = Wall(
                id=f"wall_{i}",
                x1=mx1,
                y1=my1,
                x2=mx2,
                y2=my2,
                thickness=0.2, # 기본값 설정
                height=2.5,    # 기본값 설정
                role="inner"   # 기본값 설정
            )
            processed.append(wall_obj)
            
        return processed