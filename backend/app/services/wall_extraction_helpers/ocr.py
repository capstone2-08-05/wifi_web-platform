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
        # detail=1 → bbox + text + confidence
        # paragraph=False → 각 단어 단위
        results = reader.readtext(str(image_path), detail=1, paragraph=False)
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

    logger.info("OCR detected %d text entries from %s", len(entries), image_path.name)
    return entries


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
