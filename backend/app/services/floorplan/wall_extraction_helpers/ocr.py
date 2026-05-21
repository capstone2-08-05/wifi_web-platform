"""원본 도면 이미지에서 텍스트 bbox 추출 (EasyOCR).

벽 추출 threshold 평가 시 "텍스트 영역에 벽 mask 가 잡혔으면 페널티" 로 활용.
도면의 글자/치수 라벨 (방 이름, 숫자) 위치를 알면 그 부분이 벽으로 오탐되는 걸
줄일 수 있음.

EasyOCR 모델은 최초 호출 시 ~64MB 다운로드 (한국어 + 영어). 캐싱됨.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCREntry:
    """OCR 결과 한 항목. room label / 치수 / scale calibration 확장용."""
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    text: str
    confidence: float


@lru_cache(maxsize=1)
def _get_reader():
    """프로세스당 한 번만 reader 인스턴스 생성 (모델 로드 비싸서)."""
    import easyocr
    # gpu=False — 백엔드는 보통 CPU. 추론 한 번 정도라 그렇게 느리지 않음.
    # 한국어 + 영어. 도면에 한글 라벨 (방, 주방 등) 또는 영문 (Bedroom, Kitchen) 둘 다 가능.
    return easyocr.Reader(["ko", "en"], gpu=False, verbose=False)


def detect_text_entries(image_path: Path) -> list[OCREntry]:
    """이미지에서 OCR 로 텍스트 영역 + 문자열 + 신뢰도 추출.

    문자열까지 같이 반환 — room label 자동 부여, 치수 OCR, scale calibration 같은
    후속 기능에서 활용. threshold scoring 만 필요한 호출자는 `detect_text_bboxes`
    를 쓰면 됨 (위치만 추출).

    실패 시 빈 리스트 반환 (벽 추출 흐름 계속 진행).
    """
    try:
        reader = _get_reader()
    except Exception as exc:
        logger.warning("EasyOCR reader 초기화 실패 → OCR 페널티 비활성화: %s", exc)
        return []

    try:
        import cv2
        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("OCR: 이미지 디코드 실패 %s", image_path)
            return []
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # 전체는 0° 1번, 좌/우 여백 strip 만 회전 OCR(세로 치수). rotation_info 전체 대비 비용↓.
        results = _ocr_margin_rotation(reader, rgb)
    except Exception as exc:
        logger.warning("OCR 실행 실패: %s", exc)
        return []

    entries: list[OCREntry] = []
    for entry in results:
        # entry = (bbox_4_points, text, confidence)
        if len(entry) < 3:
            continue
        bbox_pts, text, conf = entry[0], entry[1], entry[2]
        try:
            xs = [int(p[0]) for p in bbox_pts]
            ys = [int(p[1]) for p in bbox_pts]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        except (TypeError, IndexError):
            continue
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            confidence = 0.0
        entries.append(OCREntry(bbox=bbox, text=str(text), confidence=confidence))

    entries = _dedupe_entries(entries)
    logger.info("OCR detected %d text entries from %s", len(entries), image_path.name)
    return entries


def _readtext_strip(reader, rgb, x0: int, x1: int, rotate_code):
    """좌/우 strip 회전 OCR → (source 좌표 4pts, text, conf). 좌표 역매핑 포함."""
    import cv2
    strip = rgb[:, x0:x1]
    strip_h, strip_w = strip.shape[:2]
    rotated = cv2.rotate(strip, rotate_code)
    out = []
    for entry in reader.readtext(rotated, detail=1, paragraph=False):
        if len(entry) < 3:
            continue
        pts, text, conf = entry[0], entry[1], entry[2]
        try:
            mapped = []
            for p in pts:
                rx, ry = float(p[0]), float(p[1])
                if rotate_code == cv2.ROTATE_90_CLOCKWISE:
                    sx, sy = ry, (strip_h - 1) - rx
                else:  # ROTATE_90_COUNTERCLOCKWISE
                    sx, sy = (strip_w - 1) - ry, rx
                mapped.append((sx + x0, sy))
        except (TypeError, IndexError):
            continue
        out.append((mapped, text, conf))
    return out


def _ocr_margin_rotation(reader, rgb, *, strip_ratio: float = 0.16, min_strip_px: int = 40):
    """전체 0° OCR + 좌/우 여백 strip 회전 OCR. detail=1 과 동일 shape 반환."""
    import cv2
    results: list = []
    for entry in reader.readtext(rgb, detail=1, paragraph=False):
        if len(entry) >= 3:
            results.append((entry[0], entry[1], entry[2]))
    h, w = rgb.shape[:2]
    sw = min(w, max(min_strip_px, int(w * strip_ratio)))
    strips = [(0, sw)]
    if w - sw > sw:
        strips.append((w - sw, w))
    for (x0, x1) in strips:
        for code in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
            try:
                results.extend(_readtext_strip(reader, rgb, x0, x1, code))
            except Exception as exc:
                logger.warning("strip OCR 실패: %s", exc)
    return results


def _bbox_iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _dedupe_entries(entries: list[OCREntry], iou_thr: float = 0.4) -> list[OCREntry]:
    """겹치는 OCR 결과 중 confidence 높은 것만 유지 (0°/회전 패스 중복 제거)."""
    ordered = sorted(entries, key=lambda e: e.confidence, reverse=True)
    kept: list[OCREntry] = []
    for e in ordered:
        if any(_bbox_iou(e.bbox, k.bbox) > iou_thr for k in kept):
            continue
        kept.append(e)
    return kept


def detect_text_bboxes(image_path: Path) -> list[tuple[int, int, int, int]]:
    """텍스트 위치 bbox 만 추출 (threshold scoring 용 경량 진입점).

    문자열/신뢰도가 필요하면 `detect_text_entries` 를 사용. 둘은 동일한 OCR
    실행을 거치므로 중복 호출이 필요하면 호출자가 `detect_text_entries` 결과를
    재사용해서 bbox 만 골라 쓰는 게 효율적.
    """
    return [e.bbox for e in detect_text_entries(image_path)]


def build_text_mask(
    bboxes: list[tuple[int, int, int, int]],
    shape: tuple[int, int],
    pad: int = 2,
) -> np.ndarray:
    """OCR bbox 영역 = 1, 나머지 = 0 인 bool mask 생성.

    pad: bbox 주변 약간 확장해서 글자 획 인근까지 포함 (벽으로 오탐 자주 됨).
    """
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)
    for x1, y1, x2, y2 in bboxes:
        x1c = max(0, x1 - pad)
        y1c = max(0, y1 - pad)
        x2c = min(w, x2 + pad)
        y2c = min(h, y2 + pad)
        if x2c > x1c and y2c > y1c:
            mask[y1c:y2c, x1c:x2c] = True
    return mask
