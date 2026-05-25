import logging
import re
import numpy as np
import cv2
from typing import List, Any
from shapely.geometry import LineString
from shapely.ops import polygonize_full, unary_union, snap

# 변경된 경로: floorplan -> scene
from app.schemas.scene import Wall, Room

logger = logging.getLogger(__name__)


# ── 방 라벨 분류 — OCR 텍스트 → (표시이름, 종류) | None ────────────────────
# 백엔드에서 직접 분류 (AI kind 에 의존 안 함 → AI 재시작 없이도 ~호/승강기 인식).
_ROOM_NO_RE = re.compile(r"\d{2,4}\s*[호도요오]")  # 호 + OCR 오인식 변형(도/요/오)
_ROOM_KO = {
    "bathroom": ("욕실", "화장실", "샤워실"),
    "bedroom": ("안방", "침실", "방"),
    "living": ("거실",),
    "kitchen": ("주방", "부엌", "식당"),
    "entrance": ("현관",),
    "balcony": ("발코니", "베란다"),
    "storage": ("드레스룸", "다용도실", "팬트리", "창고"),
    "study": ("서재",),
    "elevator": ("승강기", "엘리베이터"),
    "stairs": ("계단",),
}
_ROOM_EN = {
    "bathroom": ("bath", "toilet", "wc", "rest"),
    "bedroom": ("bedroom", "master", "room"),
    "living": ("living",),
    "kitchen": ("kitchen", "pantry", "dining"),
    "entrance": ("entry", "entrance", "hall"),
    "balcony": ("balcony",),
    "elevator": ("elevator", "lift"),
    "stairs": ("stair",),
}


def _fuzzy_contains(text: str, word: str, max_diff: int = 1) -> bool:
    """text 안에 word 와 ≤max_diff 글자만 다른 부분문자열이 있으면 True (OCR 오인식 흡수).

    길이 2+ 단어만 — 1글자 단어는 fuzzy 가 너무 느슨해 위험.
    """
    L = len(word)
    if L < 2 or len(text) < L:
        return False
    for i in range(len(text) - L + 1):
        if sum(a != b for a, b in zip(text[i:i + L], word)) <= max_diff:
            return True
    return False


def classify_room_label(text: str) -> tuple[str, str] | None:
    """OCR 텍스트 → (표시이름, room_type). 방 라벨 아니면 None. OCR 깨짐에 관대.

    예: "201호"/"201요"/"705도"→unit, "욕실"/"여실"→bathroom,
        "E/V"/"승강기"→elevator, "KITCHEN"→kitchen.
    """
    s = (text or "").strip()
    if not s:
        return None
    # 호실: 2~4자리 숫자 + 호(또는 OCR 오인식 도/요/오). 치수(3,500/17500)와 구분됨.
    if _ROOM_NO_RE.search(s):
        return s, "unit"
    low = s.lower()
    if re.fullmatch(r"e\s*/?\s*v", low) or low == "ev":
        return "승강기", "elevator"
    # 한글 방 단어 — exact 우선, 안 되면 1글자 오차 fuzzy (욕실→여실 등).
    for rtype, words in _ROOM_KO.items():
        if any(wd in s for wd in words):
            return s, rtype
    for rtype, words in _ROOM_KO.items():
        if any(_fuzzy_contains(s, wd) for wd in words):
            return s, rtype
    for rtype, words in _ROOM_EN.items():
        if any(wd in low for wd in words):
            return s, rtype
    return None

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

    def extract_rooms_from_labels(
        self,
        walls: List[Wall],
        openings: List[Any],
        seeds: List[tuple],
        wall_thickness_px: int = 0,
    ) -> List[Room]:
        """OCR 방 라벨을 seed 로 flood-fill 해 방 영역 추출 (벽/개구부 = 장벽).

        seeds: (cx, cy, name, room_type) 픽셀 좌표 + 라벨. polygonize 가 못 닫는
        방도, 라벨이 있으면 그 자리에서 벽에 막힐 때까지 영역을 채워 방으로 만든다.
        개구부(문/창)는 장벽으로 그려 flood 가 옆방/바깥으로 새는 것 방지.
        """
        if not seeds or not walls:
            return []
        h, w = int(self.pixel_height), int(self.pixel_width)
        if h <= 0 or w <= 0:
            return []

        # 1) 장벽 마스크 = 벽(두껍게) + 개구부(채움)
        barrier = np.zeros((h, w), dtype=np.uint8)
        for wl in walls:
            t = wall_thickness_px or max(
                3, int(round((getattr(wl, "thickness", 0.15) or 0.15) / self.scale_ratio))
            )
            cv2.line(barrier, (int(wl.x1), int(wl.y1)), (int(wl.x2), int(wl.y2)), 255, t)
        for op in openings or []:
            try:
                cv2.rectangle(
                    barrier, (int(op.x1), int(op.y1)), (int(op.x2), int(op.y2)), 255, -1
                )
            except (AttributeError, TypeError, ValueError):
                continue

        # 건물 bbox 면적 (방 크기 sanity 를 scale 무관하게 — 픽셀 비율로 판정).
        bxs = [c for wl in walls for c in (wl.x1, wl.x2)]
        bys = [c for wl in walls for c in (wl.y1, wl.y2)]
        bldg_area = max(1.0, (max(bxs) - min(bxs)) * (max(bys) - min(bys)))

        # 2) free space connected components
        free = (barrier == 0).astype(np.uint8)
        num, labels, stats, _ = cv2.connectedComponentsWithStats(free, connectivity=4)

        def _comp_at(cx: int, cy: int) -> int:
            """seed 위치 컴포넌트. barrier 위면 ±6px 이웃에서 free 탐색."""
            if 0 <= cy < h and 0 <= cx < w and labels[cy, cx] != 0 and barrier[cy, cx] == 0:
                return int(labels[cy, cx])
            for r in range(1, 7):
                for dy in (-r, 0, r):
                    for dx in (-r, 0, r):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and barrier[ny, nx] == 0:
                            return int(labels[ny, nx])
            return 0

        # 3) seed → 컴포넌트별 그룹 (같은 방에 라벨 여러 개면 묶임)
        comp_names: dict[int, tuple] = {}
        for (cx, cy, name, rtype) in seeds:
            c = _comp_at(int(round(cx)), int(round(cy)))
            if c <= 0:
                continue
            comp_names.setdefault(c, (name, rtype))  # 첫 라벨 채택

        rooms: List[Room] = []
        idx = 0
        for c, (name, rtype) in comp_names.items():
            x, y, bw, bh, area_px = stats[c]
            # 이미지 전체를 덮는 컴포넌트 = 건물 바깥 → 제외
            if x <= 1 and y <= 1 and (x + bw) >= w - 1 and (y + bh) >= h - 1:
                continue
            # 크기 sanity 는 건물 bbox 대비 픽셀 비율로 (scale 불확실해도 견고).
            frac = float(area_px) / bldg_area
            if frac < 0.003 or frac > 0.6:
                continue
            area_m2 = float(area_px) * (self.scale_ratio ** 2)
            region = (labels == c).astype(np.uint8)
            cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            cnt = max(cnts, key=cv2.contourArea)
            eps = 0.01 * cv2.arcLength(cnt, True)
            poly = cv2.approxPolyDP(cnt, eps, True).reshape(-1, 2)
            if len(poly) < 3:
                continue
            pts = [[float(px), float(py)] for px, py in poly]
            cxc = float(np.mean([p[0] for p in pts]))
            cyc = float(np.mean([p[1] for p in pts]))
            rooms.append(Room(
                id=f"room_lbl_{idx}", points=pts,
                center=[round(cxc, 2), round(cyc, 2)], area=round(area_m2, 2),
                type=rtype, name=name,
            ))
            idx += 1
        logger.info("라벨 seed 방 추출: %d개 (seed %d개)", len(rooms), len(seeds))
        return rooms