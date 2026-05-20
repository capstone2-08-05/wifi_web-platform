"""sklearn GP 기반 미니멀 Bayesian Optimization (EI acquisition).

scikit-optimize 를 새 의존성으로 들이지 않으려고 직접 구현. 50회 평가 수준에선
충분히 잘 동작. n_initial random sample 후 GP fit → EI 가 최대인 후보 선정 →
objective 호출 → 반복.

`minimize` 만 노출. 외부에선 8 차원 dict 박싱/언박싱은 `runner.py` 가 책임.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

logger = logging.getLogger(__name__)


@dataclass
class BOResult:
    best_x: np.ndarray         # shape (D,)
    best_y: float              # objective at best_x (lower better)
    history_x: np.ndarray      # shape (N, D) — 평가된 모든 입력
    history_y: np.ndarray      # shape (N,)   — 평가된 모든 출력
    n_initial: int
    n_iter: int


def _expected_improvement(
    candidates: np.ndarray,
    gp: GaussianProcessRegressor,
    current_best: float,
    xi: float = 0.01,
) -> np.ndarray:
    """EI for minimization. candidates: (M, D), returns (M,)."""
    mu, sigma = gp.predict(candidates, return_std=True)
    sigma = np.maximum(sigma, 1e-9)
    improvement = current_best - mu - xi
    z = improvement / sigma
    ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)
    return np.maximum(ei, 0.0)  # type: ignore[no-any-return]


def _random_in_bounds(
    rng: np.random.Generator, bounds: np.ndarray, n: int
) -> np.ndarray:
    """bounds: (D, 2) low/high. → (n, D)."""
    low = bounds[:, 0]
    high = bounds[:, 1]
    return rng.uniform(low, high, size=(n, bounds.shape[0]))


def minimize(
    objective: Callable[[np.ndarray], float],
    bounds: Sequence[tuple[float, float]],
    *,
    n_initial: int = 12,
    n_iter: int = 38,
    n_candidates: int = 2000,
    seed: int = 42,
) -> BOResult:
    """objective 가 작아지는 x 를 찾음.

    총 evaluation 횟수 = n_initial + n_iter (기본 50).
    각 BO step 마다 GP refit + 후보 n_candidates 개에서 EI 최대 선택 → eval.
    """
    bounds_arr = np.asarray(bounds, dtype=float)
    if bounds_arr.ndim != 2 or bounds_arr.shape[1] != 2:
        raise ValueError("bounds must be shape (D, 2)")
    if np.any(bounds_arr[:, 0] >= bounds_arr[:, 1]):
        raise ValueError("each bound must have low < high")

    rng = np.random.default_rng(seed)
    D = bounds_arr.shape[0]

    xs = _random_in_bounds(rng, bounds_arr, n_initial)
    ys = np.array([float(objective(x)) for x in xs])

    kernel = (
        ConstantKernel(1.0, (1e-3, 1e3))
        * RBF(length_scale=np.ones(D), length_scale_bounds=(1e-2, 1e3))
        + WhiteKernel(noise_level=1.0, noise_level_bounds=(1e-3, 1e2))
    )

    for it in range(n_iter):
        gp = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            n_restarts_optimizer=2,
            random_state=seed + it,
        )
        try:
            gp.fit(xs, ys)
        except Exception:
            # 수치 불안정 (커널 collapse 등) 발생 시 random fallback
            logger.exception("GP fit failed on iter %d, fallback to random", it)
            next_x = _random_in_bounds(rng, bounds_arr, 1)[0]
        else:
            candidates = _random_in_bounds(rng, bounds_arr, n_candidates)
            ei = _expected_improvement(candidates, gp, current_best=float(np.min(ys)))
            best_idx = int(np.argmax(ei))
            next_x = candidates[best_idx]

        next_y = float(objective(next_x))
        xs = np.vstack([xs, next_x[None, :]])
        ys = np.append(ys, next_y)

    best_idx = int(np.argmin(ys))
    return BOResult(
        best_x=xs[best_idx],
        best_y=float(ys[best_idx]),
        history_x=xs,
        history_y=ys,
        n_initial=n_initial,
        n_iter=n_iter,
    )
