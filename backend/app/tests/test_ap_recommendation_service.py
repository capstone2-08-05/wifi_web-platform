from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.models.calibration_run import CalibrationRun
from app.core.errors import AppError
from app.schemas.rf.ap_recommendation import (
    ApRecommendationBBox,
    ApRecommendationRequest,
    ApRecommendationZone,
)
from app.services.rf.ap_recommendation_service import (
    RssiTransfer,
    _aps_for_candidate,
    _best_params_applied,
    _build_weighted_eval_points,
    _generate_candidates_for_request,
    _generate_eval_fallback_points,
    _params_from_run,
    _transfer_from_run,
    _validate_replace_target,
)
from app.services.rf.calibration_worker.path_loss import AccessPoint, CalibrationParams, Measurement


def _request(**overrides) -> ApRecommendationRequest:
    data = {"scene_version_id": uuid4(), **overrides}
    return ApRecommendationRequest(**data)


def _run(metrics_json: dict) -> CalibrationRun:
    return CalibrationRun(
        id=str(uuid4()),
        project_id=str(uuid4()),
        floor_id=str(uuid4()),
        scene_version_id=str(uuid4()),
        status="completed",
        metrics_json=metrics_json,
    )


def test_no_priority_zones_weight_all_non_excluded_points_one():
    points = [
        Measurement(x=0.0, y=0.0, rssi_dbm=0.0),
        Measurement(x=1.0, y=1.0, rssi_dbm=0.0),
    ]

    weighted = _build_weighted_eval_points(
        points,
        priority_zones=[],
        excluded_zones=[],
    )

    assert [p.weight for p in weighted] == [1.0, 1.0]


def test_priority_zones_leave_outside_points_at_default_weight():
    points = [
        Measurement(x=0.5, y=0.5, rssi_dbm=0.0),
        Measurement(x=2.0, y=2.0, rssi_dbm=0.0),
    ]
    zones = [ApRecommendationZone(x_min=0, x_max=1, y_min=0, y_max=1, weight=1.0)]

    weighted = _build_weighted_eval_points(
        points,
        priority_zones=zones,
        excluded_zones=[],
        default_unzoned_weight=0.2,
    )

    assert [p.weight for p in weighted] == [1.0, 0.2]


def test_excluded_zones_remove_eval_points():
    points = [
        Measurement(x=0.5, y=0.5, rssi_dbm=0.0),
        Measurement(x=2.0, y=2.0, rssi_dbm=0.0),
    ]
    excluded = [ApRecommendationBBox(x_min=0, x_max=1, y_min=0, y_max=1)]

    weighted = _build_weighted_eval_points(
        points,
        priority_zones=[],
        excluded_zones=excluded,
    )

    assert [(p.x, p.y) for p in weighted] == [(2.0, 2.0)]


def test_candidate_bboxes_generate_candidates_but_priority_zones_drive_eval_fallback():
    request = _request(
        candidate_bboxes=[ApRecommendationBBox(x_min=10, x_max=11, y_min=10, y_max=11)],
        priority_zones=[ApRecommendationZone(x_min=0, x_max=1, y_min=0, y_max=1, weight=1.0)],
        step_m=1.0,
    )

    assert _generate_candidates_for_request(request) == [
        (10.0, 10.0),
        (10.0, 11.0),
        (11.0, 10.0),
        (11.0, 11.0),
    ]
    assert _generate_eval_fallback_points(request) == [
        (0.0, 0.0),
        (0.0, 1.0),
        (1.0, 0.0),
        (1.0, 1.0),
    ]


def test_candidate_generation_excludes_excluded_zones():
    request = _request(
        candidate_bboxes=[ApRecommendationBBox(x_min=0, x_max=2, y_min=0, y_max=1)],
        excluded_zones=[ApRecommendationBBox(x_min=1, x_max=1, y_min=0, y_max=1)],
        step_m=1.0,
    )

    assert _generate_candidates_for_request(request) == [
        (0.0, 0.0),
        (0.0, 1.0),
        (2.0, 0.0),
        (2.0, 1.0),
    ]


def test_eval_fallback_uses_evaluation_bboxes_before_candidate_bboxes():
    request = _request(
        candidate_bboxes=[ApRecommendationBBox(x_min=10, x_max=11, y_min=10, y_max=11)],
        evaluation_bboxes=[ApRecommendationBBox(x_min=2, x_max=3, y_min=3, y_max=4)],
    )

    assert _generate_eval_fallback_points(request) == [
        (2.0, 3.0),
        (2.0, 4.0),
        (3.0, 3.0),
        (3.0, 4.0),
    ]


def test_transfer_only_policy_applies_transfer_not_best_params():
    run = _run(
        {
            "best_params": {"path_loss_exp": 4.2, "tx_power_offset_db": 9.0},
            "rssi_transfer": {"slope": 0.72, "intercept_db": -18.4},
        }
    )

    params = _params_from_run(run, "transfer_only")
    transfer = _transfer_from_run(run, "transfer_only")

    assert params == CalibrationParams()
    assert transfer.slope == pytest.approx(0.72)
    assert transfer.intercept_db == pytest.approx(-18.4)
    assert transfer.transfer_applied is True
    assert _best_params_applied(run, "transfer_only") is False


def test_best_params_only_policy_applies_best_params_with_identity_transfer():
    run = _run(
        {
            "best_params": {"path_loss_exp": 4.2, "tx_power_offset_db": 9.0},
            "rssi_transfer": {"slope": 0.72, "intercept_db": -18.4},
        }
    )

    params = _params_from_run(run, "best_params_only")
    transfer = _transfer_from_run(run, "best_params_only")

    assert params.path_loss_exp == pytest.approx(4.2)
    assert params.tx_power_offset_db == pytest.approx(9.0)
    assert transfer == RssiTransfer()
    assert _best_params_applied(run, "best_params_only") is True


def test_combined_policy_applies_best_params_and_transfer_from_same_run():
    run = _run(
        {
            "best_params": {"path_loss_exp": 3.6, "tx_power_offset_db": -1.5},
            "rssi_transfer": {"slope": 0.8, "intercept_db": -10.0},
            "residual": {"method": "idw", "weight": 0.6, "use_for_recommendation": True},
        }
    )

    params = _params_from_run(run, "combined")
    transfer = _transfer_from_run(run, "combined")

    assert params.path_loss_exp == pytest.approx(3.6)
    assert params.tx_power_offset_db == pytest.approx(-1.5)
    assert transfer.slope == pytest.approx(0.8)
    assert transfer.intercept_db == pytest.approx(-10.0)
    assert transfer.calibration_run_id == str(run.id)
    assert transfer.residual_enabled is False
    assert _best_params_applied(run, "combined") is True


def test_add_and_replace_modes_are_explicit():
    existing = [
        AccessPoint(name="ap1", x=0.0, y=0.0),
        AccessPoint(name="ap2", x=5.0, y=5.0),
    ]
    candidate = AccessPoint(name="candidate", x=1.0, y=1.0)

    add = _aps_for_candidate(
        existing_aps=existing,
        candidate_ap=candidate,
        recommendation_mode="add",
        replace_target_ap_id=None,
    )
    replace_all = _aps_for_candidate(
        existing_aps=existing,
        candidate_ap=candidate,
        recommendation_mode="replace",
        replace_target_ap_id=None,
    )
    replace_target = _aps_for_candidate(
        existing_aps=existing,
        candidate_ap=AccessPoint(name="ap1", x=1.0, y=1.0),
        recommendation_mode="replace",
        replace_target_ap_id="ap1",
    )

    assert [ap.name for ap in add] == ["ap1", "ap2", "candidate"]
    assert [ap.name for ap in replace_all] == ["candidate"]
    assert [ap.name for ap in replace_target] == ["ap2", "ap1"]


def test_replace_target_id_must_exist_in_existing_aps():
    request = _request(
        recommendation_mode="replace",
        replace_target_ap_id="missing-ap",
    )

    with pytest.raises(AppError) as exc:
        _validate_replace_target(
            request,
            [AccessPoint(name="ap1", x=0.0, y=0.0)],
        )

    assert exc.value.status_code == 400
