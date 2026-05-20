"""도면 OCR 치수 ↔ 벽 길이 매칭 + scale 자동 추정.

도면에는 보통 벽 옆에 치수 라벨이 적혀 있다 (예: "3,500", "3.5m", "350cm").
OCR 로 라벨 위치/문자열을 받고, 가장 가까운 평행 벽 선분의 픽셀 길이와 페어링하면
픽셀↔미터 변환비 (`scale_m_per_px`) 를 도면 자체에서 추정할 수 있다.

흐름:
  1. `parse_dimension_to_meters(text)` — 텍스트에서 미터값만 뽑는다 (m/mm/cm 인식).
  2. `match_dimensions_to_walls(entries, walls)` — 각 OCR 항목을 인접 벽과 짝지운다.
  3. `estimate_scale_from_matches(matches)` — 페어들의 median 으로 scale 결정 (outlier 제외).

사용자에게 도면 가로폭(m)을 묻지 않고도 scale 잡히는 것이 목적. 매칭 신뢰 페어가
부족하면 `None` 반환 → 호출자(`fusion_service`)가 default fallback scale 사용 후
사용자가 PropertiesPanel 에서 벽별 실측값으로 보정.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Sequence

logger = logging.getLogger(__name__)


# 단위 명시 패턴 (대소문자 무시). 한국 건축 도면 표기 흔한 순서대로.
_UNIT_PATTERNS: tuple[tuple[re.Pattern, float], ...] = (
    (re.compile(r"(\d+(?:[\.,]\d+)?)\s*mm\b", re.IGNORECASE), 0.001),
    (re.compile(r"(\d+(?:[\.,]\d+)?)\s*cm\b", re.IGNORECASE), 0.01),
    (re.compile(r"(\d+(?:[\.,]\d+)?)\s*m\b", re.IGNORECASE), 1.0),
)

# 단위 미명시 — 쉼표 포함 정수 ("3,500"): 한국 건축 mm 표기로 가정.
_COMMA_INT_PATTERN = re.compile(r"^\s*(\d{1,3}(?:,\d{3})+)\s*$")
# 단위 미명시 — 소수점 포함 ("3.5"): m 가정.
_DECIMAL_PATTERN = re.compile(r"^\s*(\d+\.\d+)\s*$")
# 단위 미명시 — 단순 정수 ("3500", "17500"): 한국 건축 도면은 mm 가 표준이라 mm 가정.
# 너무 작거나 큰 값은 거부 (방 번호/연도 등 오인 방지). 범위: 300~50000 mm = 0.3~50m.
_PLAIN_INT_PATTERN = re.compile(r"^\s*(\d{3,5})\s*$")
_PLAIN_INT_MIN_MM = 300
_PLAIN_INT_MAX_MM = 50000


@dataclass(frozen=True)
class ParsedDimension:
    meters: float
    confidence: float  # 단위 명시=1.0, 휴리스틱(comma/decimal)=0.5
    unit_hint: str     # "m" / "mm" / "cm" / "mm_comma" / "m_decimal"


# 흔한 OCR 글자↔숫자 오인식 보정표 (치수 토큰 한정 적용).
_OCR_DIGIT_MAP = str.maketrans({
    "O": "0", "o": "0", "D": "0",
    "I": "1", "l": "1", "|": "1",
    "Z": "2", "z": "2",
    "S": "5", "s": "5",
    "B": "8",
    "g": "9", "q": "9",
    "b": "6",
})


def _normalize_ocr_digits(text: str) -> str | None:
    """치수처럼 보이는(숫자 과반) 토큰의 글자↔숫자 오인식 보정.

    예: "50O"→"500", "44OO"→"4400". 방 라벨('KITCHEN' 등 숫자 비율 낮음)은 제외.
    보정이 일어난 경우만 결과 반환, 아니면 None.
    """
    if not text:
        return None
    s = text.strip()
    alnum = [c for c in s if c.isalnum()]
    if not alnum:
        return None
    digit_ratio = sum(c.isdigit() for c in alnum) / len(alnum)
    if digit_ratio < 0.5:  # 숫자가 과반 아니면 치수로 안 봄 → 라벨 오변환 방지
        return None
    normalized = s.translate(_OCR_DIGIT_MAP)
    return normalized if normalized != s else None


def parse_dimension_to_meters(text: str) -> ParsedDimension | None:
    """OCR 텍스트 → 미터 길이. raw 실패 시 숫자 오인식 보정 후 재시도.

    인식 규칙:
      - "3500mm" / "350cm" / "3.5m" → 명시 단위 직접 변환 (confidence=1.0)
      - "3,500" → 한국 도면 mm 가정 (confidence=0.5)
      - "3.5" → m 가정 (confidence=0.5)
      - "3500" → mm 가정 (confidence=0.3)
      - 위 모두 실패 + 숫자 과반이면 O→0 등 보정 후 재시도 (confidence ×0.8, "_ocrfix")
    """
    if not text or not isinstance(text, str):
        return None
    parsed = _parse_dimension_raw(text)
    if parsed is not None:
        return parsed
    fixed = _normalize_ocr_digits(text)
    if fixed is not None:
        parsed = _parse_dimension_raw(fixed)
        if parsed is not None:
            return ParsedDimension(
                meters=parsed.meters,
                confidence=round(parsed.confidence * 0.8, 3),
                unit_hint=parsed.unit_hint + "_ocrfix",
            )
    return None


def _parse_dimension_raw(text: str) -> ParsedDimension | None:
    """보정 없이 원문 그대로 파싱 (parse_dimension_to_meters 내부용)."""
    if not text or not isinstance(text, str):
        return None

    # 단위 명시 우선 — 텍스트 전체가 아닌 부분 매칭도 허용 (예: "L=3.5m" 등).
    for pat, factor in _UNIT_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            meters = v * factor
            if meters <= 0:
                continue
            unit = "mm" if factor == 0.001 else ("cm" if factor == 0.01 else "m")
            return ParsedDimension(meters=meters, confidence=1.0, unit_hint=unit)

    # 휴리스틱 1: 쉼표 포함 정수 → mm
    m = _COMMA_INT_PATTERN.match(text)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
        if v <= 0:
            return None
        return ParsedDimension(meters=v * 0.001, confidence=0.5, unit_hint="mm_comma")

    # 휴리스틱 2: 소수점 → m
    m = _DECIMAL_PATTERN.match(text)
    if m:
        try:
            v = float(m.group(1))
        except ValueError:
            return None
        if v <= 0 or v > 30.0:  # 30m 초과는 도면 단일 치수로 비현실적
            return None
        return ParsedDimension(meters=v, confidence=0.5, unit_hint="m_decimal")

    # 휴리스틱 3: 단순 정수 ("3500", "17500") → mm 가정 (한국 건축 표준).
    # confidence 0.3 — 단위 추정이 강한 가정이라 가장 낮음. 다른 신호와 같이 쓰일 때
    # outlier 로 떨어지면 estimate_scale_from_matches 의 MAD 필터가 걸러줌.
    m = _PLAIN_INT_PATTERN.match(text)
    if m:
        try:
            v = int(m.group(1))
        except ValueError:
            return None
        if v < _PLAIN_INT_MIN_MM or v > _PLAIN_INT_MAX_MM:
            return None
        return ParsedDimension(meters=v / 1000.0, confidence=0.3, unit_hint="mm_int")

    return None


@dataclass
class DimensionMatch:
    """OCR 치수 라벨 + 매칭된 벽 + implied scale."""
    text: str
    parsed_meters: float
    bbox: tuple[int, int, int, int]
    orientation: str  # "horizontal" / "vertical"
    matched_wall_idx: int | None
    matched_wall_px_len: float | None
    implied_scale_m_per_px: float | None
    ocr_confidence: float
    parse_confidence: float

    def is_valid_for_scale(self) -> bool:
        return (
            self.matched_wall_idx is not None
            and self.implied_scale_m_per_px is not None
            and self.implied_scale_m_per_px > 0
        )

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "parsed_meters": round(self.parsed_meters, 4),
            "bbox": list(self.bbox),
            "orientation": self.orientation,
            "matched_wall_idx": self.matched_wall_idx,
            "matched_wall_px_len": (
                round(self.matched_wall_px_len, 2)
                if self.matched_wall_px_len is not None else None
            ),
            "implied_scale_m_per_px": (
                round(self.implied_scale_m_per_px, 6)
                if self.implied_scale_m_per_px is not None else None
            ),
            "ocr_confidence": round(self.ocr_confidence, 3),
            "parse_confidence": round(self.parse_confidence, 3),
        }


def _bbox_orientation(bbox: tuple[int, int, int, int]) -> str:
    """bbox 가로/세로 비율로 치수 라벨 방향 추정 (벽도 같은 방향이라 가정)."""
    x1, y1, x2, y2 = bbox
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    return "horizontal" if w >= h else "vertical"


def _wall_orientation(wall: Sequence[float]) -> str | None:
    """벽 선분이 거의 수평/수직인지. 둘 다 아니면 None (대각선 제외)."""
    x1, y1, x2, y2 = wall
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    if dx == 0 and dy == 0:
        return None
    if dx >= dy * 3:
        return "horizontal"
    if dy >= dx * 3:
        return "vertical"
    return None


def _wall_length(wall: Sequence[float]) -> float:
    x1, y1, x2, y2 = wall
    return float(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)


def _bbox_to_wall_distance(
    bbox: tuple[int, int, int, int], wall: Sequence[float], orientation: str
) -> float:
    """치수 bbox 중심에서 평행 벽까지의 수직 거리."""
    bx = (bbox[0] + bbox[2]) / 2
    by = (bbox[1] + bbox[3]) / 2
    x1, y1, x2, y2 = wall
    wall_mid_x = (x1 + x2) / 2
    wall_mid_y = (y1 + y2) / 2
    if orientation == "horizontal":
        # 수평 벽 — y 차이가 수직 거리
        return abs(by - wall_mid_y)
    # 수직 벽 — x 차이가 수직 거리
    return abs(bx - wall_mid_x)


def _bbox_along_overlap(
    bbox: tuple[int, int, int, int], wall: Sequence[float], orientation: str
) -> float:
    """치수 bbox 가 벽 선분과 길이 방향으로 얼마나 겹치는지 (0~1)."""
    if orientation == "horizontal":
        bx1, bx2 = bbox[0], bbox[2]
        wx1, wx2 = min(wall[0], wall[2]), max(wall[0], wall[2])
    else:
        bx1, bx2 = bbox[1], bbox[3]
        wx1, wx2 = min(wall[1], wall[3]), max(wall[1], wall[3])
    inter = max(0.0, min(bx2, wx2) - max(bx1, wx1))
    span = max(1.0, bx2 - bx1)
    return float(inter / span)


def match_dimensions_to_walls(
    entries,  # list[OCREntry] (app.services.wall_extraction_helpers.ocr.OCREntry)
    walls: Sequence[Sequence[float]],
    max_perpendicular_dist_px: float = 80.0,
    min_along_overlap: float = 0.2,
) -> list[DimensionMatch]:
    """OCR 항목 각각에 가장 가까운 평행 벽을 매칭.

    매칭 규칙:
      - 라벨 bbox 방향(수평/수직) 추정 → 같은 방향 벽만 후보
      - bbox 중심에서 벽까지 수직 거리 ≤ `max_perpendicular_dist_px`
      - bbox 와 벽이 길이 방향으로 일정 비율(`min_along_overlap`) 이상 겹쳐야 함
      - 위 조건 통과한 후보 중 수직 거리가 가장 작은 벽 1개
    """
    matches: list[DimensionMatch] = []
    if not walls:
        return matches

    for entry in entries or []:
        parsed = parse_dimension_to_meters(entry.text)
        if parsed is None:
            continue

        orient = _bbox_orientation(entry.bbox)

        best_idx: int | None = None
        best_dist = float("inf")
        for i, w in enumerate(walls):
            if _wall_orientation(w) != orient:
                continue
            d = _bbox_to_wall_distance(entry.bbox, w, orient)
            if d > max_perpendicular_dist_px:
                continue
            if _bbox_along_overlap(entry.bbox, w, orient) < min_along_overlap:
                continue
            if d < best_dist:
                best_dist = d
                best_idx = i

        wall_len = _wall_length(walls[best_idx]) if best_idx is not None else None
        implied = (
            (parsed.meters / wall_len) if wall_len and wall_len > 0 else None
        )
        matches.append(
            DimensionMatch(
                text=entry.text,
                parsed_meters=parsed.meters,
                bbox=entry.bbox,
                orientation=orient,
                matched_wall_idx=best_idx,
                matched_wall_px_len=wall_len,
                implied_scale_m_per_px=implied,
                ocr_confidence=entry.confidence,
                parse_confidence=parsed.confidence,
            )
        )

    if matches:
        valid = sum(1 for m in matches if m.is_valid_for_scale())
        logger.info(
            "dimension matching: %d parsed, %d wall-matched (of %d walls)",
            len(matches), valid, len(walls),
        )
    return matches


@dataclass
class IntervalScalePair:
    """인접한 두 OCR 치수 텍스트의 중심 사이 픽셀 거리 ↔ 평균 meters 페어.

    수식: 두 인접 치수 라벨 (m1, m2) 사이 텍스트 중심 픽셀 거리 (dx) 는
      dx = (segment1_px + segment2_px) / 2
         = (m1 + m2) / 2  *  pixels_per_meter
    따라서:
      implied_scale_m_per_px = (m1 + m2) / (2 * dx)
    """
    text_a: str
    text_b: str
    meters_a: float
    meters_b: float
    bbox_a: tuple[float, float, float, float]
    bbox_b: tuple[float, float, float, float]
    center_distance_px: float
    orientation: str  # "horizontal" / "vertical"
    implied_scale_m_per_px: float
    parse_confidence_avg: float

    def to_dict(self) -> dict:
        return {
            "text_a": self.text_a,
            "text_b": self.text_b,
            "meters_a": round(self.meters_a, 4),
            "meters_b": round(self.meters_b, 4),
            "bbox_a": [round(v, 2) for v in self.bbox_a],
            "bbox_b": [round(v, 2) for v in self.bbox_b],
            "center_distance_px": round(self.center_distance_px, 2),
            "orientation": self.orientation,
            "implied_scale_m_per_px": round(self.implied_scale_m_per_px, 6),
            "parse_confidence_avg": round(self.parse_confidence_avg, 3),
        }


def find_dimension_interval_pairs(
    entries,  # list[OCREntry]
    same_line_tolerance_px: float = 60.0,
    min_center_distance_px: float = 20.0,
) -> list[IntervalScalePair]:
    """치수 OCR 들을 같은 dimension line 끼리 그룹핑 → 인접 쌍에서 scale 추출.

    1. 각 entry 의 bbox 방향(H/V)으로 분리
    2. H 그룹: y_center 가 비슷한 (±tolerance) 항목끼리 같은 라인. x_center 로 정렬.
    3. 같은 라인의 인접한 두 항목 (a, b) → 중심 거리 dx → implied_scale 계산
    4. V 그룹: 마찬가지로 x_center 비슷, y_center 정렬

    좌표계 독립: entries 의 bbox 가 어느 space (source_image / roi_image) 에 있든
    동일 space 안에서 dx 비교만 하므로 변환 불필요.
    """
    pairs: list[IntervalScalePair] = []

    horizontal: list = []
    vertical: list = []
    for e in entries or []:
        parsed = parse_dimension_to_meters(e.text)
        if parsed is None or parsed.meters <= 0:
            continue
        bbox = e.bbox
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        # 가로로 길면 H, 세로로 길면 V (정사각형 가까우면 H 우선)
        if w >= h:
            horizontal.append((e, parsed, bbox))
        else:
            vertical.append((e, parsed, bbox))

    def _process(group, axis: str):
        """axis = 'h' (수평 dimension line, x 따라 정렬) or 'v' (수직, y 따라)."""
        if len(group) < 2:
            return
        if axis == "h":
            # 같은 라인: y_center 끼리 비슷. 정렬은 x_center.
            key_along = lambda b: (b[0] + b[2]) / 2  # x_center
            key_across = lambda b: (b[1] + b[3]) / 2  # y_center
            orient = "horizontal"
        else:
            key_along = lambda b: (b[1] + b[3]) / 2  # y_center
            key_across = lambda b: (b[0] + b[2]) / 2  # x_center
            orient = "vertical"

        # 같은 라인끼리 모으기 (across 좌표를 tolerance 단위로 양자화 → 버킷)
        buckets: dict[int, list] = {}
        for item in group:
            _e, _p, bbox = item
            across = key_across(bbox)
            bucket_key = int(round(across / same_line_tolerance_px))
            buckets.setdefault(bucket_key, []).append(item)

        for bucket_items in buckets.values():
            if len(bucket_items) < 2:
                continue
            # along 좌표 기준 정렬
            bucket_items.sort(key=lambda it: key_along(it[2]))
            # 인접 쌍 walk
            for i in range(len(bucket_items) - 1):
                ea, pa, ba = bucket_items[i]
                eb, pb, bb = bucket_items[i + 1]
                ca = key_along(ba)
                cb = key_along(bb)
                dx = cb - ca
                if dx < min_center_distance_px:
                    continue
                # 부호 검증 (정렬돼 있으므로 양수여야 함)
                if dx <= 0:
                    continue
                m_avg_half = (pa.meters + pb.meters) / 2.0
                if m_avg_half <= 0:
                    continue
                implied = m_avg_half / dx
                pairs.append(
                    IntervalScalePair(
                        text_a=ea.text,
                        text_b=eb.text,
                        meters_a=pa.meters,
                        meters_b=pb.meters,
                        bbox_a=tuple(float(v) for v in ba),  # type: ignore[arg-type]
                        bbox_b=tuple(float(v) for v in bb),  # type: ignore[arg-type]
                        center_distance_px=float(dx),
                        orientation=orient,
                        implied_scale_m_per_px=float(implied),
                        parse_confidence_avg=(pa.confidence + pb.confidence) / 2.0,
                    )
                )

    _process(horizontal, "h")
    _process(vertical, "v")

    if pairs:
        logger.info(
            "dimension intervals: %d pairs (h=%d, v=%d)",
            len(pairs),
            sum(1 for p in pairs if p.orientation == "horizontal"),
            sum(1 for p in pairs if p.orientation == "vertical"),
        )
    return pairs


def estimate_scale_from_intervals(
    pairs: list[IntervalScalePair],
    min_pairs: int = 2,
    mad_factor: float = 3.0,
) -> "ScaleEstimate | None":
    """tick-interval pairs 에서 median + MAD outlier 제거로 scale 추정.

    `min_pairs=2` 가 기본 — 인접 페어가 2 개만 있어도 시도. 잘못된 단위 추정은 MAD 가
    걸러주는 구조라 wall-length 매칭보다 페어 적어도 안정적.
    """
    valid = [p for p in pairs if p.implied_scale_m_per_px > 0]
    if len(valid) < min_pairs:
        return None

    vals = sorted(p.implied_scale_m_per_px for p in valid)
    n = len(vals)
    med = vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    abs_dev = sorted(abs(v - med) for v in vals)
    mad = abs_dev[n // 2] if n % 2 == 1 else 0.5 * (abs_dev[n // 2 - 1] + abs_dev[n // 2])

    if mad == 0:
        kept = valid
    else:
        kept = [p for p in valid if abs(p.implied_scale_m_per_px - med) <= mad_factor * mad]
        if len(kept) < min_pairs:
            kept = valid

    kept_vals = sorted(p.implied_scale_m_per_px for p in kept)
    k = len(kept_vals)
    final = kept_vals[k // 2] if k % 2 == 1 else 0.5 * (kept_vals[k // 2 - 1] + kept_vals[k // 2])

    return ScaleEstimate(
        scale_m_per_px=float(final),
        pair_count=len(kept),
        median=float(med),
        mad=float(mad),
        outliers_dropped=len(valid) - len(kept),
        used_pairs=[p.to_dict() for p in kept],
    )


@dataclass
class ScaleEstimate:
    scale_m_per_px: float
    pair_count: int
    median: float
    mad: float                 # median absolute deviation
    outliers_dropped: int
    used_pairs: list[dict] = field(default_factory=list)
    # 어떤 방법으로 추정했는지 추적 — "tick_interval" 우선, fallback 시 "wall_length"
    method: str = "tick_interval"

    def to_dict(self) -> dict:
        return {
            "scale_m_per_px": round(self.scale_m_per_px, 6),
            "pair_count": self.pair_count,
            "median": round(self.median, 6),
            "mad": round(self.mad, 6),
            "outliers_dropped": self.outliers_dropped,
            "used_pairs": list(self.used_pairs),
            "method": self.method,
        }


def estimate_scale_from_matches(
    matches: list[DimensionMatch],
    min_pairs: int = 3,
    mad_factor: float = 3.0,
) -> ScaleEstimate | None:
    """매칭들에서 픽셀↔미터 변환비 추정. min_pairs 미만이면 None.

    median + MAD 기반 outlier 제거 후 median 반환. unit-mismatch (예: "3500" 을
    잘못 m 로 파싱) 같은 한두 케이스 떨어뜨려 robustness 확보.
    """
    valid = [
        m for m in matches
        if m.is_valid_for_scale() and m.implied_scale_m_per_px is not None
    ]
    if len(valid) < min_pairs:
        return None

    vals = sorted(m.implied_scale_m_per_px for m in valid)  # type: ignore[misc]
    n = len(vals)
    med = vals[n // 2] if n % 2 == 1 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])
    abs_dev = sorted(abs(v - med) for v in vals)
    mad = abs_dev[n // 2] if n % 2 == 1 else 0.5 * (abs_dev[n // 2 - 1] + abs_dev[n // 2])

    if mad == 0:
        kept = valid
    else:
        kept = [m for m in valid if abs(m.implied_scale_m_per_px - med) <= mad_factor * mad]  # type: ignore[operator]
        if len(kept) < min_pairs:
            kept = valid

    kept_vals = sorted(m.implied_scale_m_per_px for m in kept)  # type: ignore[misc]
    k = len(kept_vals)
    final = kept_vals[k // 2] if k % 2 == 1 else 0.5 * (kept_vals[k // 2 - 1] + kept_vals[k // 2])

    return ScaleEstimate(
        scale_m_per_px=float(final),
        pair_count=len(kept),
        median=float(med),
        mad=float(mad),
        outliers_dropped=len(valid) - len(kept),
        used_pairs=[m.to_dict() for m in kept],
        method="wall_length",
    )


@dataclass
class _ScaleCandidate:
    scale: float
    baseline_px: float
    source: str

    def to_dict(self) -> dict:
        return {
            "scale_m_per_px": round(self.scale, 6),
            "baseline_px": round(self.baseline_px, 1),
            "source": self.source,
        }


def _build_dimension_chains(
    entries, same_line_tolerance_px: float = 60.0
) -> dict[str, list[list[tuple[float, float]]]]:
    """같은 치수선 버킷별 [(center_along, meters), ...] (along 정렬) 체인.

    반환: {"horizontal": [chain, ...], "vertical": [chain, ...]} (각 chain 은 라벨 2개+).
    """
    horiz: list[tuple[float, float, float]] = []
    vert: list[tuple[float, float, float]] = []
    for e in entries or []:
        p = parse_dimension_to_meters(e.text)
        if p is None or p.meters <= 0:
            continue
        x1, y1, x2, y2 = e.bbox
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if (x2 - x1) >= (y2 - y1):
            horiz.append((cx, cy, p.meters))   # along=x, across=y
        else:
            vert.append((cy, cx, p.meters))    # along=y, across=x

    def _chains(items: list[tuple[float, float, float]]) -> list[list[tuple[float, float]]]:
        buckets: dict[int, list[tuple[float, float]]] = {}
        for along, across, m in items:
            k = int(round(across / same_line_tolerance_px))
            buckets.setdefault(k, []).append((along, m))
        out = []
        for b in buckets.values():
            if len(b) >= 2:
                b.sort(key=lambda t: t[0])
                out.append(b)
        return out

    return {"horizontal": _chains(horiz), "vertical": _chains(vert)}


def estimate_scale_crossvalidated(
    entries,
    walls: Sequence[Sequence[float]] | None = None,
    *,
    agree_ratio: float = 0.18,
    same_line_tolerance_px: float = 60.0,
) -> ScaleEstimate | None:
    """긴 기준선 후보들을 cluster 합의로 교차검증한 robust scale.

    짧은 인접 tick(노이즈 큼) 대신 **긴 기준선** 후보를 모아 서로 검증한다:
      - 체인 전체 span: 한 치수선의 첫~마지막 라벨 중심 사이 거리 (긴 baseline)
      - 벽 외곽 anchor: (해당 방향 최대 치수) ÷ (해당 방향 외곽 벽 픽셀 간격)
    가장 많은 후보가 동의(±agree_ratio)하는 cluster 의 median 을 채택 → 이상치 자동 배제.
    후보 없으면 None (호출자가 tick-interval 로 fallback).
    """
    cands: list[_ScaleCandidate] = []
    chains = _build_dimension_chains(entries, same_line_tolerance_px)

    # (B) 체인 전체 span — 첫~마지막 라벨 중심 사이 미터/픽셀.
    for orient, chlist in chains.items():
        for chain in chlist:
            if len(chain) < 2:
                continue
            d_px = chain[-1][0] - chain[0][0]
            if d_px <= 0:
                continue
            # 첫 중심~마지막 중심 사이 미터 = 전체합 − 첫/마지막 세그먼트 절반
            meters = sum(m for _, m in chain) - chain[0][1] / 2.0 - chain[-1][1] / 2.0
            if meters > 0:
                cands.append(_ScaleCandidate(meters / d_px, d_px, f"chain_{orient[0]}"))

    # (A) 벽 외곽 + 해당 방향 최대 치수 (전체 외곽 치수로 가정).
    if walls:
        vx = [(w[0] + w[2]) / 2.0 for w in walls if _wall_orientation(w) == "vertical"]
        hy = [(w[1] + w[3]) / 2.0 for w in walls if _wall_orientation(w) == "horizontal"]
        # max 치수는 **파싱된 모든 치수**에서 — 전체 외곽 치수(예 17,500/9,700)는 자기
        # 줄에 혼자라 체인(라벨 2개+)에 안 들어가므로 chains 만 보면 빠짐 → scale 급감 버그.
        h_dims: list[float] = []
        v_dims: list[float] = []
        for e in entries or []:
            p = parse_dimension_to_meters(e.text)
            if p is None or p.meters <= 0:
                continue
            x1b, y1b, x2b, y2b = e.bbox
            (h_dims if (x2b - x1b) >= (y2b - y1b) else v_dims).append(p.meters)
        if len(vx) >= 2 and h_dims:
            ext = max(vx) - min(vx)
            if ext > 0:
                cands.append(_ScaleCandidate(max(h_dims) / ext, ext, "wall_h"))
        if len(hy) >= 2 and v_dims:
            ext = max(hy) - min(hy)
            if ext > 0:
                cands.append(_ScaleCandidate(max(v_dims) / ext, ext, "wall_v"))

    if not cands:
        return None

    # anchor = 가장 신뢰할 후보. 벽 외곽(wall_*)을 최우선 — (전체 치수 ÷ 건물 픽셀폭)이라
    # baseline 이 가장 길고 단일 고신뢰 치수에 기반. 없으면 baseline 가장 긴 후보.
    # anchor 와 동의(±agree_ratio)하는 것만 모아 median → 짧고 noisy 한 chain 들이
    # 다수(수)로 anchor 를 이기지 못하게 함 (사용자 의도: "전체 치수를 anchor로").
    wall_cands = [c for c in cands if c.source.startswith("wall")]
    anchor = max(wall_cands or cands, key=lambda c: c.baseline_px)
    best_cluster = [
        c for c in cands if abs(c.scale - anchor.scale) <= agree_ratio * anchor.scale
    ]

    scales = sorted(c.scale for c in best_cluster)
    n = len(scales)
    final = scales[n // 2] if n % 2 else 0.5 * (scales[n // 2 - 1] + scales[n // 2])
    devs = sorted(abs(s - final) for s in scales)
    mad = devs[n // 2] if n % 2 else 0.5 * (devs[n // 2 - 1] + devs[n // 2])

    logger.info(
        "scale crossval: %d 후보 → cluster %d개 동의, scale=%.6f m/px (mad=%.6f)",
        len(cands), len(best_cluster), final, mad,
    )
    return ScaleEstimate(
        scale_m_per_px=float(final),
        pair_count=len(best_cluster),
        median=float(final),
        mad=float(mad),
        outliers_dropped=len(cands) - len(best_cluster),
        used_pairs=[c.to_dict() for c in best_cluster],
        method="anchored_crossval",
    )


def dimension_alignment_score(
    wall_mask,
    dim_entries,
    expand_perpendicular_px: int = 12,
    expand_along_px: int = 6,
) -> float:
    """치수 라벨 bbox 의 "벽 쪽" 인접 영역에 wall 픽셀이 존재하는 비율 (0~1).

    threshold_scoring 단계용 — wall 선분 추출이 끝나기 전이므로 mask 자체로만 평가.
    라벨 bbox 의 좌/우 (수평 라벨) 또는 상/하 (수직 라벨) 일정 거리 내 wall 픽셀 존재 시
    "라벨에 대응하는 벽이 있다" 로 카운트. 라벨이 N 개 중 M 개 매칭되면 M/N.
    """
    import numpy as np

    if wall_mask is None or wall_mask.sum() == 0 or not dim_entries:
        return 0.0
    h, w = wall_mask.shape
    mask_bool = wall_mask > 0

    parsed_count = 0
    matched_count = 0
    for entry in dim_entries:
        if parse_dimension_to_meters(entry.text) is None:
            continue
        parsed_count += 1
        x1, y1, x2, y2 = entry.bbox
        orient = _bbox_orientation(entry.bbox)

        if orient == "horizontal":
            # 수평 라벨 → 위/아래 wall 후보
            ay1 = max(0, y1 - expand_perpendicular_px)
            ay2 = min(h, y2 + expand_perpendicular_px)
            ax1 = max(0, x1 - expand_along_px)
            ax2 = min(w, x2 + expand_along_px)
        else:
            ay1 = max(0, y1 - expand_along_px)
            ay2 = min(h, y2 + expand_along_px)
            ax1 = max(0, x1 - expand_perpendicular_px)
            ax2 = min(w, x2 + expand_perpendicular_px)

        if ax2 > ax1 and ay2 > ay1 and mask_bool[ay1:ay2, ax1:ax2].any():
            matched_count += 1

    if parsed_count == 0:
        return 0.0
    return float(matched_count / parsed_count)


# ─────────────────────────────────────────────────────────────────────────
# 구간(span) 해석 — 치수선 세그먼트를 "그리드 사이 거리" 로 보고 벽/방에 부착
# ─────────────────────────────────────────────────────────────────────────
# 건축 도면의 치수선 세그먼트(예: 1480, 3340...)는 개별 벽 길이가 아니라 인접한
# 두 그리드(=수직/수평 벽) 사이 거리다. 치수 텍스트는 자기 세그먼트의 중앙에 오므로
# scale(m/px) 을 알면 각 세그먼트의 픽셀 양끝(tick)을 복원할 수 있고, 그 tick 을
# 가장 가까운 수직/수평 벽에 스냅하면 "이 구간은 어느 두 벽 사이" 인지 알 수 있다.
@dataclass
class DimensionSpan:
    orientation: str               # 측정 축: "horizontal"(x거리) / "vertical"(y거리)
    meters: float
    text: str
    axis_lo: float                 # 측정축 픽셀 시작 (H=x, V=y) — tick
    axis_hi: float                 # 측정축 픽셀 끝
    perp: float                    # dimension line 의 perp 좌표 (참고용)
    boundary_lo_wall: int | None   # axis_lo 쪽 경계 벽 idx (H→수직벽, V→수평벽)
    boundary_hi_wall: int | None   # axis_hi 쪽 경계 벽 idx
    parse_confidence: float

    def to_dict(self) -> dict:
        return {
            "orientation": self.orientation,
            "meters": round(self.meters, 4),
            "text": self.text,
            "axis_lo": round(self.axis_lo, 2),
            "axis_hi": round(self.axis_hi, 2),
            "perp": round(self.perp, 2),
            "boundary_lo_wall": self.boundary_lo_wall,
            "boundary_hi_wall": self.boundary_hi_wall,
            "parse_confidence": round(self.parse_confidence, 3),
        }


def _walls_extent(walls: Sequence[Sequence[float]]) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for w in walls:
        xs.extend((w[0], w[2]))
        ys.extend((w[1], w[3]))
    if not xs:
        return 0.0
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _nearest_wall_index(
    wall_mids: Sequence[tuple[int, float]], target: float, tol: float
) -> int | None:
    """(idx, mid_coord) 목록에서 target 에 가장 가까운 벽 idx (거리 ≤ tol)."""
    best_idx: int | None = None
    best_d = tol
    for idx, mid in wall_mids:
        d = abs(mid - target)
        if d <= best_d:
            best_d = d
            best_idx = idx
    return best_idx


def build_dimension_spans(
    entries,  # list[OCREntry]
    scale_m_per_px: float,
    walls: Sequence[Sequence[float]],
    *,
    same_line_tol_px: float = 60.0,
    wall_snap_ratio: float = 0.035,
    min_wall_snap_px: float = 20.0,
) -> list[DimensionSpan]:
    """치수 OCR + scale + 벽 → 구간(span) 리스트.

    각 치수 텍스트를 자기 세그먼트의 중앙으로 보고 scale 로 픽셀 길이를 복원,
    양끝 tick 을 그 측정 방향의 경계 벽(H→수직벽, V→수평벽)에 스냅한다.
    """
    if not entries or not scale_m_per_px or scale_m_per_px <= 0 or not walls:
        return []

    # (orientation, meters, center_axis, perp, conf, text)
    items: list[tuple[str, float, float, float, float, str]] = []
    for e in entries:
        parsed = parse_dimension_to_meters(e.text)
        if parsed is None:
            continue
        orient = _bbox_orientation(e.bbox)
        cx = (e.bbox[0] + e.bbox[2]) / 2.0
        cy = (e.bbox[1] + e.bbox[3]) / 2.0
        if orient == "horizontal":
            items.append(("horizontal", parsed.meters, cx, cy, parsed.confidence, str(e.text)))
        else:
            items.append(("vertical", parsed.meters, cy, cx, parsed.confidence, str(e.text)))
    if not items:
        return []

    vwalls = [
        (i, (w[0] + w[2]) / 2.0) for i, w in enumerate(walls)
        if _wall_orientation(w) == "vertical"
    ]
    hwalls = [
        (i, (w[1] + w[3]) / 2.0) for i, w in enumerate(walls)
        if _wall_orientation(w) == "horizontal"
    ]
    snap_tol = max(min_wall_snap_px, _walls_extent(walls) * wall_snap_ratio)

    spans: list[DimensionSpan] = []
    for orient in ("horizontal", "vertical"):
        group = [it for it in items if it[0] == orient]
        if not group:
            continue
        # 같은 dimension line 끼리 묶기 (perp 좌표 클러스터)
        group.sort(key=lambda it: it[3])
        chains: list[list] = []
        cur = [group[0]]
        for it in group[1:]:
            if abs(it[3] - cur[-1][3]) <= same_line_tol_px:
                cur.append(it)
            else:
                chains.append(cur)
                cur = [it]
        chains.append(cur)

        boundary_walls = vwalls if orient == "horizontal" else hwalls
        for chain in chains:
            chain.sort(key=lambda it: it[2])  # 측정축 정렬
            for (_, meters, center, perp, conf, text) in chain:
                seg_px = meters / scale_m_per_px
                lo = center - seg_px / 2.0
                hi = center + seg_px / 2.0
                spans.append(
                    DimensionSpan(
                        orientation=orient,
                        meters=meters,
                        text=text,
                        axis_lo=lo,
                        axis_hi=hi,
                        perp=perp,
                        boundary_lo_wall=_nearest_wall_index(boundary_walls, lo, snap_tol),
                        boundary_hi_wall=_nearest_wall_index(boundary_walls, hi, snap_tol),
                        parse_confidence=conf,
                    )
                )
    if spans:
        logger.info(
            "dimension spans: %d 구간 (H=%d, V=%d)",
            len(spans),
            sum(1 for s in spans if s.orientation == "horizontal"),
            sum(1 for s in spans if s.orientation == "vertical"),
        )
    return spans


def attach_spans_to_walls(
    spans: Sequence[DimensionSpan], walls: Sequence[Sequence[float]]
) -> dict[int, dict]:
    """각 경계 벽에 인접 구간 부착.

    벽 좌표 증가측(오른쪽/아래)에 붙는 구간 = `span_after_m`,
    감소측(왼쪽/위)에 붙는 구간 = `span_before_m`.
    같은 측에 여러 구간이 잡히면 parse_confidence 높은 것 유지.

    반환: `{wall_idx: {"span_before_m": .., "span_after_m": .., "*_conf": ..}}`
    """
    result: dict[int, dict] = {}

    def _put(wall_idx: int | None, key: str, sp: DimensionSpan) -> None:
        if wall_idx is None:
            return
        d = result.setdefault(wall_idx, {})
        conf_key = f"{key}_conf"
        if key in d and d.get(conf_key, 0.0) >= sp.parse_confidence:
            return
        d[key] = round(sp.meters, 3)
        d[conf_key] = round(sp.parse_confidence, 3)
        d[f"{key}_text"] = sp.text

    for sp in spans:
        # boundary_lo 벽 기준: 구간은 그 벽의 좌표 증가측에 위치 → after
        _put(sp.boundary_lo_wall, "span_after_m", sp)
        # boundary_hi 벽 기준: 구간은 그 벽의 좌표 감소측에 위치 → before
        _put(sp.boundary_hi_wall, "span_before_m", sp)
    return result


def _best_iou_span(
    spans: Sequence[DimensionSpan], lo: float, hi: float, min_iou: float = 0.5
) -> DimensionSpan | None:
    """구간들 중 [lo,hi] 와 **양 끝이 가장 일치**하는 것 (IoU ≥ min_iou).

    단순 겹침이 아니라 IoU 라서, 짧은 대상([100,200])에 전체 치수([0,1000]) 가
    매칭되는 오류를 방지한다 (전체 치수는 IoU 가 낮아 탈락).
    """
    target_len = max(1.0, hi - lo)
    best: DimensionSpan | None = None
    best_iou = min_iou
    for sp in spans:
        inter = max(0.0, min(hi, sp.axis_hi) - max(lo, sp.axis_lo))
        union = max(hi, sp.axis_hi) - min(lo, sp.axis_lo)
        if union <= 0:
            continue
        iou = inter / union
        if iou >= best_iou:
            best_iou = iou
            best = sp
    _ = target_len  # (가독성용 — 길이 자체는 IoU 에 내포)
    return best


def attach_wall_lengths_parallel(
    spans: Sequence[DimensionSpan],
    walls: Sequence[Sequence[float]],
    scale_m_per_px: float | None = None,
    *,
    length_tol: float = 0.12,
) -> dict[int, dict]:
    """각 벽에 길이 부착 — 평행 치수(도면값) + scale 로 계산한 실제 길이로 검증.

    세로벽 ↔ 세로 치수(y 범위), 가로벽 ↔ 가로 치수(x 범위) IoU 매칭. 단, **매칭된
    치수가 벽의 실제 길이(픽셀×scale)와 ±length_tol 안에서 일치할 때만** 도면값으로
    인정 → "거의 full-width 내벽이 전체 치수(17,500)에 과매칭"되는 오류 차단.
    일치 안 하면 계산 길이만 표시(source="computed").

    반환: `{wall_idx: {"meters", "text"(도면값일 때만), "source": "dimension"|"computed"}}`
    """
    vspans = [s for s in spans if s.orientation == "vertical"]
    hspans = [s for s in spans if s.orientation == "horizontal"]
    has_scale = bool(scale_m_per_px and scale_m_per_px > 0)
    result: dict[int, dict] = {}
    for idx, w in enumerate(walls):
        orient = _wall_orientation(w)
        if orient == "vertical":
            lo, hi = sorted((w[1], w[3]))   # y 범위
            sp = _best_iou_span(vspans, lo, hi)
        elif orient == "horizontal":
            lo, hi = sorted((w[0], w[2]))   # x 범위
            sp = _best_iou_span(hspans, lo, hi)
        else:
            continue

        computed_m = (hi - lo) * scale_m_per_px if has_scale else None  # type: ignore[operator]

        # 도면 치수가 실제 길이와 충분히 일치하면 도면값 채택.
        if sp is not None and (
            computed_m is None
            or abs(sp.meters - computed_m) <= length_tol * computed_m
        ):
            result[idx] = {
                "meters": round(sp.meters, 3),
                "text": sp.text,
                "source": "dimension",
                "parse_confidence": round(sp.parse_confidence, 3),
            }
        elif computed_m is not None and computed_m > 0:
            # 도면 치수 없거나 불일치 → scale 계산 길이만.
            result[idx] = {
                "meters": round(computed_m, 3),
                "text": None,
                "source": "computed",
            }
    return result


def attach_spans_to_rooms(
    spans: Sequence[DimensionSpan], rooms: Sequence[dict]
) -> dict[int, dict]:
    """각 방 bbox 의 가로/세로 범위에 **양 끝이 일치**하는 구간을 width/height 로 부착.

    반환: `{room_idx: {"width_m": .., "height_m": ..}}` (매칭된 축만 채움)
    """
    hspans = [s for s in spans if s.orientation == "horizontal"]
    vspans = [s for s in spans if s.orientation == "vertical"]
    result: dict[int, dict] = {}
    for ridx, room in enumerate(rooms):
        pts = room.get("points") or []
        xs = [p[0] for p in pts if len(p) >= 2]
        ys = [p[1] for p in pts if len(p) >= 2]
        if not xs or not ys:
            continue
        d: dict = {}
        w = _best_iou_span(hspans, min(xs), max(xs))
        if w is not None:
            d["width_m"] = round(w.meters, 3)
            d["width_text"] = w.text
        h = _best_iou_span(vspans, min(ys), max(ys))
        if h is not None:
            d["height_m"] = round(h.meters, 3)
            d["height_text"] = h.text
        if d:
            result[ridx] = d
    return result
