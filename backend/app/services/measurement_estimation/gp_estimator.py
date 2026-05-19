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
    )
