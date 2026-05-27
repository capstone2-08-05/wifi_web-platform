"""측정 sparse N개 점 → Gaussian Process Regression → 도면 dense RSSI map 추정.

기술적 접근:
  - scikit-learn `GaussianProcessRegressor` 사용 — 핵심 수학 (kernel posterior,
    hyperparameter MLE) 은 라이브러리가 처리. 본 모듈은 wrapper.
  - 커널: ConstantKernel × RBF + WhiteKernel
      * RBF length_scale = 공간 상관관계 거리 (3m default — 일반 실내 환경)
      * WhiteKernel = 측정 노이즈 (±2dB default — Wi-Fi RSSI 전형값)
  - 결과: 각 grid 셀에 (mean, std) 동시 제공 — uncertainty quantification

length_scale / noise_level 은 initial value 이고, `n_restarts_optimizer` 가
MLE 로 자동 튜닝함. 실데이터에 맞춰지므로 초기값에 크게 민감하지 않음.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

logger = logging.getLogger(__name__)


@dataclass
class CoverageEstimate:
    """GP 보간 결과."""

    mean_grid: np.ndarray   # (H, W) RSSI 평균 예측 (dBm)
    std_grid: np.ndarray    # (H, W) 불확실성 표준편차 (dB)
    xs: np.ndarray          # (W,) grid x 좌표 (m)
    ys: np.ndarray          # (H,) grid y 좌표 (m)
    input_point_count: int  # 입력 측정점 개수
    kernel_repr: str        # 학습 후 kernel string (디버깅)
    method: str = "gp_only" # 'gp_only' 또는 'residual_kriging'


def estimate_coverage(
    points: list[tuple[float, float, float]],
    bounds: tuple[float, float, float, float],
    grid_resolution_m: float = 0.5,
    initial_length_scale_m: float = 3.0,
    initial_noise_db: float = 2.0,
) -> CoverageEstimate:
    """측정점 → GP fit → dense grid 예측.

    Args:
        points: (x_m, y_m, rssi_dbm) 리스트. 최소 3개 필요.
        bounds: (min_x, min_y, max_x, max_y) 도면 영역 (m).
        grid_resolution_m: 출력 grid 셀 크기 (m). 작을수록 정밀, 비쌈.
        initial_length_scale_m: RBF kernel length scale 초기값. 자동 튜닝됨.
        initial_noise_db: 측정 노이즈 초기값. 자동 튜닝됨.

    Returns:
        CoverageEstimate (mean_grid, std_grid, xs, ys, ...).

    Raises:
        ValueError: 측정점이 3개 미만이면 GP 학습 불안정 → 거부.
    """
    if len(points) < 3:
        raise ValueError(
            f"At least 3 measurement points required for GP estimation (got {len(points)})"
        )

    # 1. 데이터 분리
    arr = np.asarray(points, dtype=np.float64)
    X = arr[:, :2]          # (N, 2)
    y = arr[:, 2]           # (N,)

    # 2. GP 정의
    # ConstantKernel: 신호 분산 (자동 튜닝)
    # RBF: 공간 상관관계 (length_scale 자동 튜닝)
    # WhiteKernel: 측정 노이즈 (noise_level 자동 튜닝)
    kernel = (
        ConstantKernel(constant_value=1.0, constant_value_bounds=(1e-2, 1e3))
        * RBF(length_scale=initial_length_scale_m, length_scale_bounds=(0.5, 50.0))
        + WhiteKernel(
            noise_level=initial_noise_db, noise_level_bounds=(0.1, 50.0)
        )
    )
    gp = GaussianProcessRegressor(
        kernel=kernel,
        n_restarts_optimizer=5,
        normalize_y=True,
        random_state=42,
    )

    # 3. 학습 (N 작아도 빠름. 200점 기준 1초 이내)
    gp.fit(X, y)
    logger.info(
        "GP fitted: N=%d, kernel=%s, log_marginal_likelihood=%.2f",
        len(points), gp.kernel_, gp.log_marginal_likelihood_value_,
    )

    # 4. 도면 grid 생성
    min_x, min_y, max_x, max_y = bounds
    xs = np.arange(min_x, max_x + 1e-9, grid_resolution_m)
    ys = np.arange(min_y, max_y + 1e-9, grid_resolution_m)
    grid_X, grid_Y = np.meshgrid(xs, ys)
    grid_points = np.column_stack([grid_X.ravel(), grid_Y.ravel()])

    # 5. 예측 (mean + std)
    mean, std = gp.predict(grid_points, return_std=True)

    H, W = len(ys), len(xs)
    return CoverageEstimate(
        mean_grid=mean.reshape(H, W),
        std_grid=std.reshape(H, W),
        xs=xs,
        ys=ys,
        input_point_count=len(points),
        kernel_repr=str(gp.kernel_),
        method="gp_only",
    )


def _sample_grid_bilinear(
    grid: np.ndarray,
    grid_xs: np.ndarray,
    grid_ys: np.ndarray,
    x: float,
    y: float,
) -> float:
    """grid 의 (x, y) 미터 좌표에서 bilinear interpolation 값. bounds 밖이면 NaN."""
    if grid.size == 0 or grid_xs.size < 2 or grid_ys.size < 2:
        return float("nan")
    if x < grid_xs[0] or x > grid_xs[-1] or y < grid_ys[0] or y > grid_ys[-1]:
        return float("nan")
    dx = grid_xs[1] - grid_xs[0]
    dy = grid_ys[1] - grid_ys[0]
    fx = (x - grid_xs[0]) / dx
    fy = (y - grid_ys[0]) / dy
    i0 = int(np.floor(fy))
    j0 = int(np.floor(fx))
    i1 = min(i0 + 1, grid.shape[0] - 1)
    j1 = min(j0 + 1, grid.shape[1] - 1)
    wy = fy - i0
    wx = fx - j0
    v00 = grid[i0, j0]
    v01 = grid[i0, j1]
    v10 = grid[i1, j0]
    v11 = grid[i1, j1]
    return float(
        (1 - wy) * ((1 - wx) * v00 + wx * v01)
        + wy * ((1 - wx) * v10 + wx * v11)
    )


def estimate_coverage_residual(
    points: list[tuple[float, float, float]],
    sim_grid: np.ndarray,
    sim_xs: np.ndarray,
    sim_ys: np.ndarray,
    *,
    initial_length_scale_m: float = 3.0,
    initial_noise_db: float = 2.0,
) -> CoverageEstimate:
    """Residual kriging — 시뮬 prediction 을 prior 로 깔고 GP 가 residual 만 보간.

    측정점이 sparse 해도 시뮬의 spatial structure 가 유지돼서 단조로운 분포 안 됨.
    Bayesian 관점: posterior = prior(sim) + GP(measured − sim_at_measurement).

    Args:
        points: (x_m, y_m, rssi_dbm) 측정점.
        sim_grid: (H, W) 시뮬 예측 RSSI grid (dBm).
        sim_xs, sim_ys: grid x/y 좌표 배열 (m).

    Returns:
        CoverageEstimate (method='residual_kriging').

    Raises:
        ValueError: 측정점 < 3 또는 모든 점이 sim grid bounds 밖.
    """
    if len(points) < 3:
        raise ValueError(
            f"At least 3 measurement points required for residual kriging (got {len(points)})"
        )

    # sim grid 의 invalid 셀 (-200 이하 = Sionna 의 "시뮬 불가" sentinel + 노이즈) 을 마스킹.
    # 이 값들이 residual 에 섞이면 final = sim+residual 이 -260 같은 비현실 값까지 떨어짐 →
    # color scale 가 망가져 사용자가 보는 히트맵이 한쪽 색에 쏠림.
    # NaN 으로 바꿔두면 final grid 에서도 NaN 으로 남고, 색 범위 계산이 그것들을 무시함.
    _SIM_INVALID_THRESHOLD = -150.0  # Wi-Fi 실내 noise floor 보다 한참 아래
    sim_grid_masked = np.where(sim_grid > _SIM_INVALID_THRESHOLD, sim_grid, np.nan)

    # 각 측정점에서 sim 예측값 sampling → residual = measured - sim.
    # NaN (bounds 밖) 인 점은 제외.
    residual_points: list[tuple[float, float, float]] = []
    for x, y, rssi in points:
        sim_at_point = _sample_grid_bilinear(sim_grid_masked, sim_xs, sim_ys, x, y)
        if not np.isfinite(sim_at_point):
            continue
        residual_points.append((x, y, rssi - sim_at_point))

    if len(residual_points) < 3:
        raise ValueError(
            f"Need at least 3 measurement points inside sim bounds "
            f"(got {len(residual_points)} after filtering)"
        )

    # GP fit residual — residual 은 본질적으로 smooth 하므로 length scale 약간 크게.
    arr = np.asarray(residual_points, dtype=np.float64)
    X = arr[:, :2]
    y_resid = arr[:, 2]

    kernel = (
        ConstantKernel(constant_value=1.0, constant_value_bounds=(1e-2, 1e3))
        * RBF(length_scale=initial_length_scale_m, length_scale_bounds=(0.5, 50.0))
        + WhiteKernel(noise_level=initial_noise_db, noise_level_bounds=(0.1, 50.0))
    )
    gp = GaussianProcessRegressor(
        kernel=kernel,
        n_restarts_optimizer=5,
        normalize_y=True,
        random_state=42,
    )
    gp.fit(X, y_resid)

    grid_X, grid_Y = np.meshgrid(sim_xs, sim_ys)
    grid_points = np.column_stack([grid_X.ravel(), grid_Y.ravel()])
    resid_mean, resid_std = gp.predict(grid_points, return_std=True)

    H, W = sim_grid.shape
    # invalid sim 셀은 NaN 으로 마스킹된 grid 사용 → final 에서도 NaN 유지.
    final_mean = sim_grid_masked + resid_mean.reshape(H, W)
    # 실내 Wi-Fi 의 물리적 한계 ([-100, 0] dBm) 로 clamp — outlier 가 color scale 망가뜨리는 거 방지.
    # NaN 은 clip 결과도 NaN 으로 보존됨 (heatmap renderer 가 transparent / invalid 처리).
    final_mean = np.clip(final_mean, -100.0, 0.0)
    # std 는 residual GP 의 std 그대로 — sim 은 deterministic 가정.
    final_std = resid_std.reshape(H, W)

    logger.info(
        "Residual kriging fitted: N=%d, kernel=%s, residual_mean=%.2f, residual_std=%.2f",
        len(residual_points), gp.kernel_,
        float(np.mean(y_resid)), float(np.std(y_resid)),
    )

    return CoverageEstimate(
        mean_grid=final_mean,
        std_grid=final_std,
        xs=sim_xs,
        ys=sim_ys,
        input_point_count=len(residual_points),
        kernel_repr=str(gp.kernel_),
        method="residual_kriging",
    )
