"""GP 보간 결과 → matplotlib heatmap PNG → S3 업로드.

mean heatmap (예측 RSSI) 과 uncertainty heatmap (표준편차) 두 개 PNG 생성.
mean 은 warm-thermal 컬러맵 (frontend rssi-colormap.ts 와 동일 palette),
uncertainty 는 흑백 계열 사용.
"""
from __future__ import annotations
from .gp_estimator import CoverageEstimate
from app.services import _s3
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

import io
import logging
import uuid

import matplotlib

matplotlib.use("Agg")  # 서버 환경 — GUI backend 비활성

# frontend rssi-colormap.ts 의 RSSI_HEATMAP_STOPS_RGB 와 동일한 stops.
# t=0 (weak) → medium blue, t=1 (strong) → medium-bright red.
_RSSI_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "wifi_thermal",
    [
        np.array([30,  80, 235]) / 255,
        np.array([ 0, 140, 255]) / 255,
        np.array([ 0, 210, 255]) / 255,
        np.array([ 0, 240, 190]) / 255,
        np.array([30, 240,  70]) / 255,
        np.array([160, 240,   0]) / 255,
        np.array([255, 235,   0]) / 255,
        np.array([255, 160,   0]) / 255,
        np.array([255,  55,   0]) / 255,
        np.array([235,   0,   0]) / 255,
        np.array([195,   0,   0]) / 255,
    ],
)


logger = logging.getLogger(__name__)


# 색 스케일 fallback / minimum span — measurement 점이 1~2개라 GP mean grid spread 가
# 거의 0 일 때 vmin≈vmax 가 되어 전체가 colormap 한 색으로 깔리는 버그 방지.
_MEAN_FALLBACK_VMIN_DBM = -95.0
_MEAN_FALLBACK_VMAX_DBM = -35.0
_MEAN_MIN_SPAN_DB = 12.0


# 실내 Wi-Fi RSSI 물리적 noise floor — 이하 값은 시뮬 invalid 셀의 sentinel (-200, -270 등) 이라
# 의미 없음. p5/p95 계산 시 제외해야 color scale 가 망가지지 않음.
_NOISE_FLOOR_DBM = -120.0


def _resolve_mean_color_limits(grid: np.ndarray) -> tuple[float, float]:
    """grid mean 의 p5~p95. spread 너무 좁거나 비유한값이면 fallback / mean ± span/2.

    Wi-Fi noise floor (-120dBm) 이하는 시뮬 invalid sentinel 이거나 잡음이므로 제외.
    sionna_artifacts.resolve_radiomap_color_limits 와 동일 패턴 — 일관성.
    """
    if grid is None or grid.size == 0:
        return (_MEAN_FALLBACK_VMIN_DBM, _MEAN_FALLBACK_VMAX_DBM)
    finite = grid[np.isfinite(grid)]
    # noise floor 이하는 색 스케일 결정에서 제외 — invalid sim 셀이 -200 ~ -270 정도라
    # 포함 시 p5 가 그쪽으로 끌려가서 색이 한쪽에 쏠림.
    valid = finite[finite > _NOISE_FLOOR_DBM]
    if valid.size == 0:
        return (_MEAN_FALLBACK_VMIN_DBM, _MEAN_FALLBACK_VMAX_DBM)
    lo, hi = np.percentile(valid, [5.0, 95.0])
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return (_MEAN_FALLBACK_VMIN_DBM, _MEAN_FALLBACK_VMAX_DBM)
    if float(hi - lo) < _MEAN_MIN_SPAN_DB:
        # 측정점 sparse → GP 가 prior mean 으로 단조롭게 깔림 → spread 좁음.
        # 평균 중심으로 min span 만큼 강제 확장 → colormap 끝색 한가지로 안 깔림.
        mid = float(np.mean(valid))
        half = _MEAN_MIN_SPAN_DB / 2.0
        return (mid - half, mid + half)
    return (float(lo), float(hi))


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
    """grid → 컬러맵 적용한 raw PNG bytes (chrome 없음).

    프론트가 PNG 전체를 bounds 사각형에 stretch 하기 때문에 축/제목/컬러바 같은
    matplotlib chrome 이 박히면 데이터 영역이 어긋남. axes 만 figure 전체에 깔고
    축 끄기 + padding 0 으로 저장 — PNG 한 픽셀이 grid 한 셀.
    """
    H, W = grid.shape
    fig = plt.figure(figsize=(W / 100.0, H / 100.0), dpi=100, frameon=False)
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_axis_off()
    ax.imshow(
        grid,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="bilinear",
        aspect="auto",
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", pad_inches=0)
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
        [(p[0], p[1])
         for p in measurement_points] if measurement_points else None
    )

    mean = estimate.mean_grid
    std = estimate.std_grid

    # mean 색 범위 — _resolve_mean_color_limits 가 narrow spread / NaN / empty 안전 처리.
    mean_vmin, mean_vmax = _resolve_mean_color_limits(mean)
    mean_png = _render_to_png(
        mean,
        estimate.xs,
        estimate.ys,
        cmap=_RSSI_CMAP,
        vmin=mean_vmin,
        vmax=mean_vmax,
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
