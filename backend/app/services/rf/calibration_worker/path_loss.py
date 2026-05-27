"""자체 path-loss 모델 (BO 의 fast objective).

Sionna 한 번 돌리는 데 분 단위 걸리므로, BO 의 50회 평가를 위해 빠른
근사 모델이 필요. 다음 항만 고려한 단순 log-distance + wall attenuation:

  RSSI_pred(p) = max( TX_dBm + tx_offset_dB
                      - PL0_dB - 10*n*log10(d / d0)
                      - Σ_walls (att_per_m * thickness * scale),
                      RSSI_FLOOR )

기여하는 BO 변수:
  - tx_power_offset_db                       → 전체 가산
  - materials.{m}.attenuation_scale          → 각 벽 감쇠량 배수
  - scene_defaults.floor_thickness_m         → 천장/바닥 통과 (현 모델은 미반영,
                                               향후 multi-floor 확장 시)
  - scene_defaults.furniture_default_thickness_m
                                             → material=None 인 벽의 기본 두께

좌표 단위는 모두 미터. 거리/두께는 평면 (xy) 기준.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# 상수
# ────────────────────────────────────────────────────────────────────
# log-distance 모델 파라미터 (실내 2.4GHz 일반값)
PL0_DB = 40.0          # d0=1m 기준 reference path loss
PATH_LOSS_EXP = 3.0    # 실내 다중경로 환경 경험값
REF_DISTANCE_M = 1.0
RSSI_FLOOR_DBM = -110.0
DEFAULT_TX_POWER_DBM = 20.0

# 재질별 dB/m 감쇠 (ITU-R P.2040 표 기반 근사, 2.4GHz)
ATTENUATION_DB_PER_M: dict[str, float] = {
    "concrete": 40.0,
    "brick": 20.0,
    "drywall": 4.0,
    "plasterboard": 4.0,
    "wood": 5.0,
    "glass": 6.0,
    "metal": 80.0,
    "marble": 30.0,
    "plywood": 5.0,
    "chipboard": 6.0,
    "ceiling_board": 4.0,
    "floorboard": 5.0,
}
FALLBACK_ATTENUATION_DB_PER_M = 6.0  # material_label 이 None / 미지인 벽

# BO 가 다루는 5 개 재질 (그 외 재질은 fallback scale 1.0 사용)
CALIBRATABLE_MATERIALS: tuple[str, ...] = (
    "drywall", "concrete", "wood", "glass", "metal"
)


# ────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ────────────────────────────────────────────────────────────────────
@dataclass
class AccessPoint:
    name: str
    x: float
    y: float
    tx_power_dbm: float = DEFAULT_TX_POWER_DBM


@dataclass
class WallSegment:
    """벽 한 조각. centerline 의 두 끝점 + 두께 + 재질."""
    x1: float
    y1: float
    x2: float
    y2: float
    thickness_m: float
    material: str | None  # ATTENUATION_DB_PER_M 의 key 또는 None


@dataclass
class Measurement:
    """측정 1개. (x, y) 위치 + 실측 RSSI."""
    x: float
    y: float
    rssi_dbm: float


@dataclass
class CalibrationParams:
    """BO 변수 → 모델 파라미터.

    path_loss_exp: log-distance 모델의 n. 공간 유형별 prior 로 초기값/bounds 가
    달라지지만 absolute value 로 저장 (delta 가 아님 — 해석 가능성 ↑).
    PL0_DB 는 BO 변수로 안 둠 — tx_power_offset_db 와 식별성이 겹쳐 잡음.
    """
    tx_power_offset_db: float = 0.0
    # log-distance exponent. 디폴트는 generic indoor (모듈 상수 PATH_LOSS_EXP).
    # SPACE_PRIORS 가 None 이거나 미지정 시 fallback.
    path_loss_exp: float = PATH_LOSS_EXP
    floor_thickness_m: float = 0.10
    furniture_default_thickness_m: float = 0.05
    # material_label → scale (없으면 1.0)
    material_attenuation_scales: dict[str, float] = field(default_factory=dict)

    def scale_for(self, material: str | None) -> float:
        if material is None:
            return 1.0
        return self.material_attenuation_scales.get(material, 1.0)


# ────────────────────────────────────────────────────────────────────
# 기하: 측정점 → AP 선분이 벽 선분을 가로지르나
# ────────────────────────────────────────────────────────────────────
def _segments_cross(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> bool:
    """선분 AB 와 CD 가 교차(공선 포함 X)하는지. 표준 orientation 판정."""

    def _ori(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> int:
        val = (qy - py) * (rx - qx) - (qx - px) * (ry - qy)
        if abs(val) < 1e-9:
            return 0
        return 1 if val > 0 else -1

    o1 = _ori(ax, ay, bx, by, cx, cy)
    o2 = _ori(ax, ay, bx, by, dx, dy)
    o3 = _ori(cx, cy, dx, dy, ax, ay)
    o4 = _ori(cx, cy, dx, dy, bx, by)
    return o1 != o2 and o3 != o4


def _wall_attenuation_db(
    ap: AccessPoint, m: Measurement, walls: Sequence[WallSegment],
    params: CalibrationParams,
) -> float:
    total = 0.0
    for w in walls:
        if not _segments_cross(ap.x, ap.y, m.x, m.y, w.x1, w.y1, w.x2, w.y2):
            continue
        base = ATTENUATION_DB_PER_M.get(
            (w.material or "").lower(),
            FALLBACK_ATTENUATION_DB_PER_M,
        )
        thickness = w.thickness_m
        if thickness is None or thickness <= 0:
            thickness = params.furniture_default_thickness_m
        scale = params.scale_for((w.material or "").lower() or None)
        total += base * thickness * scale
    return total


# ────────────────────────────────────────────────────────────────────
# 핵심 예측 함수
# ────────────────────────────────────────────────────────────────────
def predict_rssi(
    ap: AccessPoint,
    point: Measurement,
    walls: Sequence[WallSegment],
    params: CalibrationParams,
) -> float:
    dx = point.x - ap.x
    dy = point.y - ap.y
    d = math.hypot(dx, dy)
    d = max(d, REF_DISTANCE_M)

    # path-loss exponent: params 가 우선 (공간 유형별 BO 결과). 0 이하면 모듈 상수로 폴백.
    n = params.path_loss_exp if params.path_loss_exp > 0 else PATH_LOSS_EXP
    fspl_term = PL0_DB + 10.0 * n * math.log10(d / REF_DISTANCE_M)
    wall_term = _wall_attenuation_db(ap, point, walls, params)
    rssi = ap.tx_power_dbm + params.tx_power_offset_db - fspl_term - wall_term
    return max(rssi, RSSI_FLOOR_DBM)


def predict_rssi_best_ap(
    aps: Sequence[AccessPoint],
    point: Measurement,
    walls: Sequence[WallSegment],
    params: CalibrationParams,
) -> float:
    """여러 AP 중 가장 강한 신호 (실측이 BSSID 미지정인 경우의 근사)."""
    best = RSSI_FLOOR_DBM
    for ap in aps:
        v = predict_rssi(ap, point, walls, params)
        if v > best:
            best = v
    return best


# ────────────────────────────────────────────────────────────────────
# 메트릭
# ────────────────────────────────────────────────────────────────────
@dataclass
class RssiErrorMetrics:
    rmse_dbm: float
    mae_dbm: float
    n_points: int


def compute_error_metrics(
    aps: Sequence[AccessPoint],
    walls: Sequence[WallSegment],
    measurements: Iterable[Measurement],
    params: CalibrationParams,
) -> RssiErrorMetrics:
    """측정 ↔ 예측 RSSI RMSE / MAE.

    measurements 는 rssi_dbm 이 채워진 것만 들어와야 함 (None 필터링은 호출자 책임).
    """
    se = 0.0
    ae = 0.0
    n = 0
    for m in measurements:
        pred = predict_rssi_best_ap(aps, m, walls, params)
        err = pred - m.rssi_dbm
        se += err * err
        ae += abs(err)
        n += 1
    if n == 0:
        return RssiErrorMetrics(rmse_dbm=0.0, mae_dbm=0.0, n_points=0)
    return RssiErrorMetrics(
        rmse_dbm=math.sqrt(se / n),
        mae_dbm=ae / n,
        n_points=n,
    )
