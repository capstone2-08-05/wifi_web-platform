"""여러 threshold 후보 중 best 선택.

각 threshold 마다 wall mask 만들고, 6가지 점수로 평가:
  + line_alignment_score : 추출된 직선 (Hough) 과 wall mask 의 겹침
  + connectivity_score   : mask 연결성 (큰 연결 컴포넌트 위주, 작은 노이즈 적을수록 ↑)
  + orthogonal_score     : 수평/수직 픽셀 비율 (대각선 노이즈 ↓)
  + dimension_alignment  : OCR 치수 라벨 옆에 wall 픽셀 존재 비율 (라벨 ↔ 벽 정합)
  - ocr_penalty          : OCR 텍스트 bbox 안에 wall 픽셀이 얼마나 들어갔는지
  - noise_penalty        : 작은 isolated 컴포넌트 개수 (정규화)

가중치는 디폴트 1.0 으로 시작. 실데이터 보면서 조정 가능.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)


DEFAULT_THRESHOLDS = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)


@dataclass
class ThresholdScore:
    threshold: float
    line_alignment: float
    connectivity: float
    orthogonal: float
    ocr_penalty: float
    noise_penalty: float
    dimension_alignment: float
    total: float

    def to_dict(self) -> dict:
        """JSON 직렬화용 (응답 / summary_json 영속화)."""
        return {
            "threshold": round(self.threshold, 4),
            "line_alignment": round(self.line_alignment, 4),
            "connectivity": round(self.connectivity, 4),
            "orthogonal": round(self.orthogonal, 4),
            "ocr_penalty": round(self.ocr_penalty, 4),
            "noise_penalty": round(self.noise_penalty, 4),
            "dimension_alignment": round(self.dimension_alignment, 4),
            "total": round(self.total, 4),
        }


def _line_alignment_score(wall_mask: np.ndarray, line_mask: np.ndarray) -> float:
    """추출 선분과 wall mask 의 IoU 비스무리 (선분 픽셀 중 wall 영역에 들어간 비율)."""
    if line_mask.sum() == 0 or wall_mask.sum() == 0:
        return 0.0
    line_pix = (line_mask > 0)
    wall_pix = (wall_mask > 0)
    inter = (line_pix & wall_pix).sum()
    return float(inter / line_pix.sum())


def _connectivity_score(wall_mask: np.ndarray) -> float:
    """큰 connected component 위주면 1 에 가깝, 작은 조각 많으면 0 에 가깝."""
    if wall_mask.sum() == 0:
        return 0.0
    num_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(
        (wall_mask > 0).astype(np.uint8), connectivity=8
    )
    if num_labels <= 1:  # 배경만
        return 0.0
    # 가장 큰 컴포넌트가 차지하는 비율 (배경 제외)
    areas = stats[1:, cv2.CC_STAT_AREA]
    if len(areas) == 0:
        return 0.0
    return float(areas.max() / areas.sum())


def _orthogonal_score(wall_mask: np.ndarray) -> float:
    """수평/수직 픽셀 비율. Sobel 응답으로 근사."""
    if wall_mask.sum() == 0:
        return 0.0
    mask8 = (wall_mask > 0).astype(np.uint8) * 255
    sx = cv2.Sobel(mask8, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(mask8, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(sx * sx + sy * sy)
    edge_pix = mag > 50
    total = int(edge_pix.sum())
    if total == 0:
        return 0.0
    # |gx| 또는 |gy| 가 압도적이면 수평/수직 픽셀로 카운트
    asx = np.abs(sx)
    asy = np.abs(sy)
    horiz = ((asy > asx * 3) & edge_pix).sum()
    vert = ((asx > asy * 3) & edge_pix).sum()
    return float((horiz + vert) / total)


def _ocr_penalty(wall_mask: np.ndarray, text_mask: np.ndarray) -> float:
    """텍스트 영역 안에 들어간 wall 픽셀 비율. 높을수록 나쁨."""
    if text_mask.sum() == 0 or wall_mask.sum() == 0:
        return 0.0
    overlap = ((wall_mask > 0) & text_mask).sum()
    return float(overlap / wall_mask.sum())


def _noise_penalty(wall_mask: np.ndarray, min_area_ratio: float = 0.001) -> float:
    """작은 컴포넌트 개수 비율. 0~1 정규화 (10개 이상이면 1)."""
    if wall_mask.sum() == 0:
        return 0.0
    h, w = wall_mask.shape
    min_area = max(5, int(h * w * min_area_ratio))
    num_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(
        (wall_mask > 0).astype(np.uint8), connectivity=8
    )
    small = sum(
        1 for i in range(1, num_labels) if stats[i, cv2.CC_STAT_AREA] < min_area
    )
    return float(min(1.0, small / 10.0))


def score_threshold(
    prob_map: np.ndarray,
    threshold: float,
    line_mask: np.ndarray | None,
    text_mask: np.ndarray | None,
    dim_entries=None,
    weights: tuple[float, float, float, float, float, float] = (1.0, 1.0, 1.0, 1.0, 0.5, 1.0),
) -> ThresholdScore:
    """단일 threshold 평가.

    weights: (line_alignment, connectivity, orthogonal, ocr_penalty, noise_penalty,
    dimension_alignment). 디폴트는 dim_alignment 도 line_alignment 와 동급 1.0.
    """
    wall_mask = (prob_map > threshold).astype(np.uint8) * 255

    la = _line_alignment_score(wall_mask, line_mask) if line_mask is not None else 0.0
    cc = _connectivity_score(wall_mask)
    orth = _orthogonal_score(wall_mask)
    ocr_p = _ocr_penalty(wall_mask, text_mask) if text_mask is not None else 0.0
    np_pen = _noise_penalty(wall_mask)
    dim = 0.0
    if dim_entries:
        # 지연 import — dimension_matching 이 ocr 모듈을 거치지 않도록.
        from app.services.wall_extraction_helpers.dimension_matching import (
            dimension_alignment_score,
        )
        dim = dimension_alignment_score(wall_mask, dim_entries)

    w_la, w_cc, w_orth, w_ocr, w_np, w_dim = weights
    total = (
        w_la * la + w_cc * cc + w_orth * orth + w_dim * dim
        - w_ocr * ocr_p - w_np * np_pen
    )

    return ThresholdScore(
        threshold=float(threshold),
        line_alignment=la,
        connectivity=cc,
        orthogonal=orth,
        ocr_penalty=ocr_p,
        noise_penalty=np_pen,
        dimension_alignment=dim,
        total=total,
    )


def pick_best_threshold(
    prob_map: np.ndarray,
    line_mask: np.ndarray | None,
    text_mask: np.ndarray | None,
    dim_entries=None,
    candidates: tuple[float, ...] = DEFAULT_THRESHOLDS,
) -> tuple[float, list[ThresholdScore]]:
    """모든 후보 평가 후 best (threshold, scores 전체 리스트) 반환."""
    scores = [
        score_threshold(prob_map, t, line_mask, text_mask, dim_entries=dim_entries)
        for t in candidates
    ]
    best = max(scores, key=lambda s: s.total)
    logger.info(
        "threshold scoring: best=%.2f total=%.3f "
        "(la=%.3f, cc=%.3f, orth=%.3f, dim=%.3f, ocr_p=%.3f, np=%.3f)",
        best.threshold, best.total, best.line_alignment, best.connectivity,
        best.orthogonal, best.dimension_alignment, best.ocr_penalty, best.noise_penalty,
    )
    return best.threshold, scores
