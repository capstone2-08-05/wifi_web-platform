"""원본 도면 이미지에서 긴 직선 후보 추출 (Canny + HoughLinesP).

벽 추출 threshold 평가 시 "추출된 선분이 wall mask 와 잘 겹치는가" 측정용.
도면 벽은 보통 긴 수평/수직 직선이므로, U-Net mask 와 이 선분이 align 되면
벽일 가능성이 큼 → threshold 가 적절했다는 신호.

LSD (LineSegmentDetector) 가 더 정확하지만 OpenCV 4.x 에서 제거됨
(SBM-Net 라이선스 이슈). HoughLinesP 로 충분히 실용적.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def detect_line_segments(
    image_path: Path,
    canny_low: int = 50,
    canny_high: int = 150,
    hough_threshold: int = 80,
    min_line_length_ratio: float = 0.10,
    max_line_gap: int = 10,
    angle_tolerance_deg: float = 5.0,
) -> np.ndarray:
    """이미지에서 **벽 후보** 직선 추출 (N, 4) `[x1, y1, x2, y2]`.

    raw Hough → 해칭/치수선/가구까지 다 잡혀서 노이즈 많음. 벽 후보로 좁히기 위해:
      - `min_line_length_ratio` 0.10 (도면 짧은 변의 10% 이상) — 짧은 가구/디테일 제거
      - 수평/수직만 (`angle_tolerance_deg` 이내) — 대각선/해칭 제거
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        logger.warning("line detection: 이미지 읽기 실패 %s", image_path)
        return np.empty((0, 4), dtype=np.int32)

    h, w = img.shape
    min_length = max(20, int(min(h, w) * min_line_length_ratio))

    edges = cv2.Canny(img, canny_low, canny_high, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_length,
        maxLineGap=max_line_gap,
    )
    if lines is None:
        return np.empty((0, 4), dtype=np.int32)

    segs = lines.reshape(-1, 4)
    raw_count = len(segs)

    # 수평/수직 필터: 각도가 0° 또는 90° 근처인 것만.
    if angle_tolerance_deg > 0 and raw_count > 0:
        dx = segs[:, 2] - segs[:, 0]
        dy = segs[:, 3] - segs[:, 1]
        # arctan2 결과를 0~90° 로 fold (수평/수직 모두 0 또는 90 근처가 됨)
        angle = np.degrees(np.arctan2(np.abs(dy), np.abs(dx)))  # 0~90
        horiz = angle <= angle_tolerance_deg
        vert = angle >= (90.0 - angle_tolerance_deg)
        segs = segs[horiz | vert]

    logger.info(
        "line detection: %d → %d segments (min_length=%d, ±%.1f° H/V)",
        raw_count, len(segs), min_length, angle_tolerance_deg,
    )
    return segs


def build_line_mask(
    segments: np.ndarray, shape: tuple[int, int], thickness: int = 3
) -> np.ndarray:
    """선분들을 픽셀 mask 로 렌더. wall mask 와 정합도 측정용."""
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)
    for x1, y1, x2, y2 in segments:
        cv2.line(mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, thickness)
    return mask
