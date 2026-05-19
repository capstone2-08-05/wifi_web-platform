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


def parse_dimension_to_meters(text: str) -> ParsedDimension | None:
    """OCR 텍스트에서 미터 단위 길이 추출. 인식 안되면 None.

    인식 규칙:
      - "3500mm" / "350cm" / "3.5m" → 명시된 단위로 직접 변환 (confidence=1.0)
      - "3,500" → 한국 도면 mm 표기로 가정 (confidence=0.5)
      - "3.5" → m 가정 (confidence=0.5)
      - 단순 정수 (e.g. "350") → 단위 추정 위험 → 거부
    """
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
class ScaleEstimate:
    scale_m_per_px: float
    pair_count: int
    median: float
    mad: float                 # median absolute deviation
    outliers_dropped: int
    used_pairs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scale_m_per_px": round(self.scale_m_per_px, 6),
            "pair_count": self.pair_count,
            "median": round(self.median, 6),
            "mad": round(self.mad, 6),
            "outliers_dropped": self.outliers_dropped,
            "used_pairs": list(self.used_pairs),
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
