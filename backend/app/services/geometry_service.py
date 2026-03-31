class GeometryService:
    def __init__(self, pixel_width: int, pixel_height: int, real_width_m: float):
        # 1픽셀당 몇 미터인지 (Scale Ratio)
        self.scale_ratio = real_width_m / pixel_width
        self.pixel_height = pixel_height

    def convert_pixel_to_meter(self, px: float, py: float):
        mx = px * self.scale_ratio
        my = py * self.scale_ratio # 필요시 (self.pixel_height - py)로 Y축 반전
        return round(mx, 3), round(my, 3)

    def process_ai_walls(self, wall_data: list):
        processed = []
        for i, coords in enumerate(wall_data):
            start = self.convert_pixel_to_meter(coords[0], coords[1])
            end = self.convert_pixel_to_meter(coords[2], coords[3])
            processed.append({
                "id": i,
                "start_pos": start,
                "end_pos": end
            })
        return processed