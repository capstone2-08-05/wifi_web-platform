"""calibration best_params 를 RF 시뮬 입력(scene_json/simulation)에 반영 (#88).

SageMaker RF 컨테이너는 correction_profile 필드를 안 받으므로, 보정값을
scene/simulation 값에 미리 녹여서(mutation) 전달한다. 컨테이너 수정 불필요.

SageMaker 경로에서 표현 가능한 보정 (4개 중 2개, 고영향):
  - 재질 attenuation_scale → wall thickness 에 곱함
      (공용 런타임 수식 effective_thickness = geometric × scale 와 동일 효과)
  - tx_power_offset_db     → simulation.tx_power_dbm 에 더함

표현 불가 (컨테이너 하드코딩, 저영향 — 추후 컨테이너가 correction_profile 지원하면 추가):
  - floor_thickness_m
  - furniture_default_thickness_m
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calibration_run import CalibrationRun

logger = logging.getLogger(__name__)


# calibration material key → scene.json (Sionna) material key.
# scene_version_export 의 MATERIAL_ALIAS 와 일치해야 함 (drywall→plasterboard 등).
_CALIB_TO_SIONNA: dict[str, str] = {
    "drywall": "plasterboard",
    "concrete": "concrete",
    "wood": "wood",
    "glass": "glass",
    "metal": "metal",
}
_SIONNA_TO_CALIB: dict[str, str] = {v: k for k, v in _CALIB_TO_SIONNA.items()}


def get_latest_calibration(
    db: Session, scene_version_id: str
) -> CalibrationRun | None:
    """해당 scene_version 의 가장 최근 completed CalibrationRun. 없으면 None."""
    return db.execute(
        select(CalibrationRun)
        .where(
            CalibrationRun.scene_version_id == str(scene_version_id),
            CalibrationRun.status == "completed",
        )
        .order_by(CalibrationRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def apply_to_scene_and_sim(
    scene_json: dict[str, Any],
    simulation: dict[str, Any],
    best_params: dict[str, Any],
) -> dict[str, Any]:
    """scene_json.walls 두께 + simulation.tx_power_dbm 을 보정값으로 in-place 조정.

    반환: 적용 요약 dict (감사/디버그용). scene_json / simulation 은 직접 수정됨.
    """
    scales: dict[str, float] = best_params.get("material_attenuation_scales") or {}
    tx_offset = float(best_params.get("tx_power_offset_db") or 0.0)

    # 1) 재질별 attenuation_scale → wall thickness 배수
    walls = scene_json.get("walls") or []
    scaled_count = 0
    for w in walls:
        sionna_mat = str(w.get("material") or "").lower()
        calib_key = _SIONNA_TO_CALIB.get(sionna_mat, sionna_mat)
        scale = scales.get(calib_key)
        if scale is not None and scale > 0:
            w["thickness"] = float(w.get("thickness") or 0.12) * float(scale)
            scaled_count += 1

    # 2) tx_power_offset_db → simulation.tx_power_dbm
    tx_applied = False
    if tx_offset and "tx_power_dbm" in simulation:
        simulation["tx_power_dbm"] = float(simulation["tx_power_dbm"]) + tx_offset
        tx_applied = True

    summary = {
        "walls_scaled": scaled_count,
        "tx_power_offset_db_applied": tx_offset if tx_applied else 0.0,
        "material_scales": scales,
        # SageMaker 경로에선 미반영 (참고용 — 컨테이너가 correction_profile 지원하면 활성)
        "unapplied": {
            "floor_thickness_m": best_params.get("floor_thickness_m"),
            "furniture_default_thickness_m": best_params.get("furniture_default_thickness_m"),
        },
    }
    logger.info(
        "calibration applied to RF input: %d walls scaled, tx_offset=%.2f",
        scaled_count, tx_offset if tx_applied else 0.0,
    )
    return summary
