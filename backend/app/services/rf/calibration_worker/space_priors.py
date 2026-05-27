"""공간 유형별 path-loss surrogate model 의 soft prior config.

## 왜 필요한가

Calibration BO 의 fast objective 인 path-loss 모델은 다음 식을 쓴다.

    RSSI = TX + offset - PL0 - 10*n*log10(d/d0) - Σ(att·thickness·scale)

이 중 `n` (path-loss exponent) 은 공간 유형마다 다른 값이 자연스럽다 — 카페/오피스는
가구·사람 흡수로 큰 n, 강의실은 개방형이라 작은 n, 원룸은 비교적 작은 n 등.

기존엔 `PATH_LOSS_EXP=3.0` 고정이라 BO 가 거리 감쇠 mismatch 를 material_scale 이나
tx_power_offset 으로 잘못 흡수했음. 이 모듈은 **공간 유형을 hint 로 받아 BO 의**
**탐색 범위/초기값을 다르게 잡는 soft prior** 역할.

## 핵심 원칙

- **Hard rule 아님**. "카페면 n=3.8" 처럼 강제 X — BO 가 measurements 기반으로 최종 결정.
- prior 는 **bounds 와 init** 만 좁혀줌. measurements 가 다른 값을 강하게 시사하면 BO 가
  그 방향으로 이동 가능.
- 잘못된 space_type 이 와도 안전하도록 bounds 를 과하게 좁히지 않음.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Final, TypedDict


class SpaceType(StrEnum):
    """공간 유형 — 사용자 선택 또는 scene metadata 에서 옴.

    `unknown` 은 미지정/분류 애매 → generic indoor prior 사용.
    """
    CAFE = "cafe"
    STUDY_ROOM = "study_room"
    CLASSROOM = "classroom"
    OFFICE = "office"
    RESIDENTIAL = "residential"
    UNKNOWN = "unknown"


class SpacePrior(TypedDict):
    """공간 유형 1개에 대한 calibration prior."""
    path_loss_exp_init: float
    path_loss_exp_bounds: tuple[float, float]
    furniture_default_thickness_init: float
    material_scale_bounds: dict[str, tuple[float, float]]
    description: str   # 짧은 영문 식별자 (i18n/UI 분기용)


# 초기 heuristic — 실험 데이터로 추후 조정 가능.
# bounds 가 과하게 좁아 BO 가 잘못된 space_type 에 갇히지 않도록, low~high 폭은 1.5~2.5 유지.
SPACE_PRIORS: Final[dict[SpaceType, SpacePrior]] = {
    SpaceType.CAFE: {
        "path_loss_exp_init": 3.4,
        "path_loss_exp_bounds": (2.6, 4.3),
        "furniture_default_thickness_init": 0.10,
        "material_scale_bounds": {
            "drywall":  (0.5, 3.0),
            "concrete": (0.5, 3.5),
            "wood":     (0.5, 3.0),
            "glass":    (0.5, 3.0),
            "metal":    (0.5, 4.0),
        },
        "description": "furniture_and_people_dense",
    },
    SpaceType.STUDY_ROOM: {
        "path_loss_exp_init": 3.3,
        "path_loss_exp_bounds": (2.6, 4.0),
        "furniture_default_thickness_init": 0.08,
        "material_scale_bounds": {
            "drywall":  (0.5, 3.5),
            "concrete": (0.5, 3.0),
            "wood":     (0.5, 2.5),
            "glass":    (0.5, 3.5),
            "metal":    (0.5, 3.0),
        },
        "description": "partition_and_small_rooms",
    },
    SpaceType.CLASSROOM: {
        "path_loss_exp_init": 2.8,
        "path_loss_exp_bounds": (2.0, 3.6),
        "furniture_default_thickness_init": 0.05,
        "material_scale_bounds": {
            "drywall":  (0.5, 2.5),
            "concrete": (0.5, 3.0),
            "wood":     (0.5, 2.5),
            "glass":    (0.5, 2.5),
            "metal":    (0.5, 3.0),
        },
        "description": "open_large_room",
    },
    SpaceType.OFFICE: {
        "path_loss_exp_init": 3.2,
        "path_loss_exp_bounds": (2.4, 4.1),
        "furniture_default_thickness_init": 0.08,
        "material_scale_bounds": {
            "drywall":  (0.5, 3.0),
            "concrete": (0.5, 3.0),
            "wood":     (0.5, 3.0),
            "glass":    (0.5, 3.5),
            "metal":    (0.5, 4.0),
        },
        "description": "partition_glass_metal_mixed",
    },
    SpaceType.RESIDENTIAL: {
        "path_loss_exp_init": 2.6,
        "path_loss_exp_bounds": (1.8, 3.4),
        "furniture_default_thickness_init": 0.05,
        "material_scale_bounds": {
            "drywall":  (0.5, 2.5),
            "concrete": (0.5, 3.0),
            "wood":     (0.5, 2.5),
            "glass":    (0.5, 2.0),
            "metal":    (0.5, 2.5),
        },
        "description": "small_residential_space",
    },
    SpaceType.UNKNOWN: {
        # generic indoor — 가장 넓은 bound. 잘못된 분류 시 안전망.
        "path_loss_exp_init": 3.0,
        "path_loss_exp_bounds": (1.8, 4.5),
        "furniture_default_thickness_init": 0.05,
        "material_scale_bounds": {
            "drywall":  (0.3, 3.0),
            "concrete": (0.3, 3.0),
            "wood":     (0.3, 3.0),
            "glass":    (0.3, 3.0),
            "metal":    (0.3, 3.0),
        },
        "description": "generic_indoor",
    },
}


def resolve_space_type(value: str | None) -> SpaceType:
    """문자열 → SpaceType. 미지정/오타/None 모두 UNKNOWN 으로 안전 fallback."""
    if not value:
        return SpaceType.UNKNOWN
    try:
        return SpaceType(value.strip().lower())
    except ValueError:
        return SpaceType.UNKNOWN


def get_prior(space_type: SpaceType) -> SpacePrior:
    """SPACE_PRIORS lookup. 매핑에 없으면 UNKNOWN fallback (안전망)."""
    return SPACE_PRIORS.get(space_type, SPACE_PRIORS[SpaceType.UNKNOWN])


# ============================================================
# 사용자용 피드백 (공간 유형별 calibration 결과 해석)
# ============================================================
# 결과 RMSE 가 baseline 대비 줄었을 때 보여줄 문구. 수치 자체는 호출자가 가공해서 합침.
SPACE_FEEDBACK_MESSAGES: Final[dict[SpaceType, str]] = {
    SpaceType.CAFE: (
        "실측 결과, 가구/좌석 밀집 구역에서 예측보다 신호가 약하게 나타났습니다. "
        "카페 환경에서는 사람·가구·유리면 반사 및 흡수 영향으로 RSSI 변동성이 커질 수 있습니다. "
        "AP 를 좌석 중앙부에 더 가깝게 배치하거나 보조 AP 추가를 검토할 수 있습니다."
    ),
    SpaceType.STUDY_ROOM: (
        "방 사이 벽 또는 유리 파티션을 통과한 뒤 신호 감쇠가 크게 나타났습니다. "
        "스터디룸처럼 작은 방이 분리된 구조에서는 복도 중앙보다 각 방 입구 또는 공용 공간에 "
        "AP 를 배치하는 것이 유리할 수 있습니다."
    ),
    SpaceType.CLASSROOM: (
        "공간이 넓어 AP 와 멀어질수록 신호가 점진적으로 감소하는 패턴이 나타났습니다. "
        "벽보다 거리 기반 감쇠가 주요 원인으로 보이며, 후방 좌석 커버리지를 위해 "
        "AP 위치 조정 또는 추가 설치가 필요할 수 있습니다."
    ),
    SpaceType.OFFICE: (
        "회의실·파티션·유리벽 또는 금속 가구 주변에서 예측과 실측 차이가 발생했을 수 있습니다. "
        "업무 공간에서는 회의실 내부와 공용 좌석 구역을 분리해 AP 배치를 검토하는 것이 좋습니다."
    ),
    SpaceType.RESIDENTIAL: (
        "소형 주거 공간에서는 공유기 위치와 벽 1~2개 통과 여부가 Wi-Fi 품질에 큰 영향을 줄 수 있습니다. "
        "공유기를 방 모서리보다 중앙부 또는 주요 사용 공간 근처에 배치하는 것이 유리할 수 있습니다."
    ),
    SpaceType.UNKNOWN: (
        "공간 유형이 지정되지 않아 일반적인 실내 prior 로 보정을 수행했습니다. "
        "프로젝트/층 설정에서 공간 유형을 지정하면 더 정확한 진단이 가능합니다."
    ),
}


def get_feedback_message(space_type: SpaceType) -> str:
    return SPACE_FEEDBACK_MESSAGES.get(
        space_type, SPACE_FEEDBACK_MESSAGES[SpaceType.UNKNOWN]
    )
