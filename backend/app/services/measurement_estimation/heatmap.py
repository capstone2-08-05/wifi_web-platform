"""GP 보간 결과 → matplotlib heatmap PNG → S3 업로드.

mean heatmap (예측 RSSI) 과 uncertainty heatmap (표준편차) 두 개 PNG 생성.
mean 은 jet/viridis 같은 신호 강도 컬러맵, uncertainty 는 흑백 / hot 컬러맵 사용.
"""
from __future__ import annotations

import io
import logging
import uuid

import matplotlib

matplotlib.use("Agg")  # 서버 환경 — GUI backend 비활성
import matplotlib.pyplot as plt
import numpy as np

from app.services import _s3
from .gp_estimator import CoverageEstimate

logger = logging.getLogger(__name__)


def _render_to_png(
    grid: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    cmap: str,
    vmin: float | None,
    vmax: float | None,
    title: str,
    colorbar_label: str,
    overlay_points: list[tuple[float, float]] | None = None,
) -> bytes:
    """grid + 컬러맵 → PNG bytes. 좌표축 = 미터."""
    H, W = grid.shape
    # 도면 비율 그대로 (figsize 약간 조정)
    aspect = (xs[-1] - xs[0]) / max(ys[-1] - ys[0], 1e-6)
    fig_h = 6
    fig_w = max(4.0, min(16.0, fig_h * aspect))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=120)
    im = ax.imshow(
        grid,
        extent=(xs[0], xs[-1], ys[-1], ys[0]),  # y 뒤집기 — top_left 원점
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="bilinear",
        aspect="auto",
    )
    if overlay_points:
        pxs = [p[0] for p in overlay_points]
        pys = [p[1] for p in overlay_points]
        ax.scatter(pxs, pys, s=8, c="white", edgecolors="black", linewidths=0.5, alpha=0.8)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(title)
    cb = plt.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label(colorbar_label)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def render_and_upload(
    estimate: CoverageEstimate,
    session_id: str,
    measurement_points: list[tuple[float, float, float]] | None = None,
) -> tuple[str, str]:
    """mean / uncertainty 두 PNG 생성 + S3 업로드 → (mean_uri, uncertainty_uri).

    Args:
        estimate: GP 결과.
        session_id: S3 키 구성용.
        measurement_points: 측정점 (x, y, rssi). mean 위에 오버레이.

    Returns:
        (mean_s3_uri, uncertainty_s3_uri) — s3:// 형식.
    """
    overlay = (
        [(p[0], p[1]) for p in measurement_points] if measurement_points else None
    )

    mean = estimate.mean_grid
    std = estimate.std_grid

    # mean 색 범위: -100 ~ -30 dBm (Wi-Fi RSSI 일반)
    mean_png = _render_to_png(
        mean,
        estimate.xs,
        estimate.ys,
        cmap="jet",
        vmin=float(np.percentile(mean, 5)),
        vmax=float(np.percentile(mean, 95)),
        title=f"Estimated RSSI Coverage (GP, N={estimate.input_point_count})",
        colorbar_label="RSSI (dBm)",
        overlay_points=overlay,
    )

    # uncertainty: 0 ~ max 자동
    std_png = _render_to_png(
        std,
        estimate.xs,
        estimate.ys,
        cmap="hot",
        vmin=0.0,
        vmax=float(std.max()) if std.size > 0 else 1.0,
        title="GP Uncertainty (std)",
        colorbar_label="std (dB)",
        overlay_points=overlay,
    )

    # S3 업로드
    job_uuid = uuid.uuid4().hex
    mean_key = f"measurement-estimates/{session_id}/{job_uuid}-mean.png"
    std_key = f"measurement-estimates/{session_id}/{job_uuid}-uncertainty.png"
    mean_uri = _s3.upload_bytes(mean_key, mean_png, content_type="image/png")
    std_uri = _s3.upload_bytes(std_key, std_png, content_type="image/png")

    logger.info(
        "GP coverage PNGs uploaded session=%s mean=%s std=%s",
        session_id, mean_uri, std_uri,
    )
    return mean_uri, std_uri
