import logging
import numpy as np
from typing import List, Any
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union, snap

# 변경된 경로: floorplan -> scene
from app.schemas.scene import Wall, Room

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_SCALE_M_PER_PX = 0.01  # OCR 치수 추정 실패 시 임시값 (1px = 1cm).
# 명백히 잘못된 추정 가능성 있음 — 사용자가 PropertiesPanel 에서 벽별 실측값 입력해
# 보정하도록 유도. summary_json["wall_postprocess"]["scale_source"]="default_fallback".


class GeometryService:
    def __init__(
        self,
        pixel_width: int,
        pixel_height: int,
        scale_ratio: float | None = None,
    ):
        # scale_ratio 결정 (m/px): 호출자가 명시한 값 우선, 없으면 default fallback.
        # real_width_m 입력 흐름은 제거됨 — OCR 치수 자동 추정이 primary source.
        if scale_ratio is not None and scale_ratio > 0:
            self.scale_ratio = float(scale_ratio)
        else:
            self.scale_ratio = DEFAULT_FALLBACK_SCALE_M_PER_PX
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
        
        # 벽 안쪽 면 기준 가용 면적 계산을 위해 안쪽으로 수축.
        # 폴리곤은 벽 '중심선' 으로 그려지므로(LineString w.x1,y1→x2,y2),
        # 중심선 → 안쪽 면 거리는 벽 두께의 절반이다 → thickness/2 만큼만 수축.
        # 두께는 calibrate_walls 가 문 폭으로 추정해 각 wall.thickness 에 채워둔 실측값 사용
        # (calibrate 전이거나 thickness 미설정 시에만 0.15m fallback).
        thicknesses = [
            float(w.thickness) for w in walls
            if getattr(w, "thickness", None) and w.thickness > 0
        ]
        wall_thickness_m = float(np.median(thicknesses)) if thicknesses else 0.15
        shrink_dist = (wall_thickness_m / 2.0) / self.scale_ratio

        # 노이즈 단순화 tolerance (좌표 extent 의 0.5%, 최소 2px).
        simplify_tol = max(2.0, coord_range * 0.005)

        for poly in polygons:
            # (1) 안쪽으로 수축 (벽 중심선 → 안쪽 면, 두께 절반)
            inner_poly = poly.buffer(-shrink_dist)
            if inner_poly.is_empty:
                continue
            # buffer 결과가 MultiPolygon 이면 가장 큰 조각만.
            if inner_poly.geom_type == "MultiPolygon":
                inner_poly = max(inner_poly.geoms, key=lambda g: g.area)
            # (2) 실제 벽 모양 유지 (envelope 사각형 대신) — 잔잔한 노이즈만 단순화.
            shape = inner_poly.simplify(simplify_tol, preserve_topology=True)
            if not shape.is_valid:
                shape = shape.buffer(0)
            if shape.is_empty or shape.geom_type != "Polygon":
                continue

            # (3) 면적 계산 (m²)
            real_area = shape.area * (self.scale_ratio ** 2)

            # 너무 작거나(노이즈) 너무 큰(외곽선) 공간 필터링
            if real_area < 2.0 or real_area > 300.0:
                continue

            # (4) Room 객체 생성 — 실제 폴리곤 외곽 좌표 그대로.
            coords = [list(pt) for pt in shape.exterior.coords]
            rooms.append(Room(
                id=f"room_{valid_room_count}",
                points=coords,
                center=[round(shape.centroid.x, 3), round(shape.centroid.y, 3)],
                area=round(real_area, 2)
            ))
            valid_room_count += 1

        logger.info(f"방 추출 완료: {len(rooms)}개의 방 생성")
        return rooms

    def calibrate_walls(self, walls: List[Wall], detections: List[Any]) -> List[Wall]:
        """벽 역할(외벽/내벽)을 추정해 현실적인 두께를 차등 적용.

        한국 주거 기준: 외벽·세대간벽은 두껍고(~0.2m 콘크리트), 내부 칸막이는
        얇다(~0.12m). 문 폭으로 기준 두께를 잡되, 건물 외곽(bbox 경계)에 있는 벽은
        외벽으로 보고 두껍게, 안쪽 벽은 얇게.
        """
        if not walls:
            return []

        # 문의 폭으로 기준(외벽) 두께 추정 — 상식 범위(0.15~0.25m) 벗어나면 0.2m.
        door_px_widths = []
        for d in detections:
            label = getattr(d, 'class_name', getattr(d, 'class', None))
            if label == "door":
                bx1, by1, bx2, by2 = d.bbox_xyxy
                door_px_widths.append(min(abs(bx2 - bx1), abs(by2 - by1)))
        if door_px_widths:
            est = (sum(door_px_widths) / len(door_px_widths)) * self.scale_ratio
            exterior_t = est if 0.15 <= est <= 0.25 else 0.2
        else:
            exterior_t = 0.2
        interior_t = round(exterior_t * 0.6, 3)  # 내벽은 외벽의 ~60% (칸막이)

        # 건물 외곽 bbox + 경계 판정 margin (전체 extent 의 4%).
        xs = [c for w in walls for c in (w.x1, w.x2)]
        ys = [c for w in walls for c in (w.y1, w.y2)]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        margin = max(8.0, max(max_x - min_x, max_y - min_y) * 0.04)

        ext_n = 0
        for wall in walls:
            is_ext = self._wall_is_exterior(wall, min_x, max_x, min_y, max_y, margin)
            wall.thickness = round(exterior_t, 3) if is_ext else interior_t
            wall.role = "outer" if is_ext else "inner"
            ext_n += 1 if is_ext else 0

        logger.info(
            "벽 두께 보정: 외벽 %.3fm(%d개) / 내벽 %.3fm(%d개)",
            exterior_t, ext_n, interior_t, len(walls) - ext_n,
        )
        return walls

    @staticmethod
    def _wall_is_exterior(w: Wall, min_x, max_x, min_y, max_y, margin: float) -> bool:
        """벽이 건물 외곽(bbox 경계)에 평행하게 붙어 있으면 외벽으로 판정."""
        dx, dy = abs(w.x2 - w.x1), abs(w.y2 - w.y1)
        if dx >= dy:  # 수평 벽 → 위/아래 경계 근처면 외벽
            y_mid = (w.y1 + w.y2) / 2.0
            return abs(y_mid - min_y) <= margin or abs(y_mid - max_y) <= margin
        # 수직 벽 → 좌/우 경계 근처면 외벽
        x_mid = (w.x1 + w.x2) / 2.0
        return abs(x_mid - min_x) <= margin or abs(x_mid - max_x) <= margin