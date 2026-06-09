from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

backend_dir = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(backend_dir))

from app.core.errors import AppError
from app.schemas.rf.physical_ap import PhysicalApInput, RadioInterfaceInput
from app.schemas.rf.rf_run import AccessPointDTO, BandSimulationParams, RfRunCreate
from app.services.rf.physical_ap_helpers import group_radios_by_band
from app.services.rf.rf_run_service import _prepare_rf_submit_from_payload


def _payload(**overrides) -> RfRunCreate:
    data = {"scene_version_id": uuid4(), **overrides}
    return RfRunCreate(**data)


def _dual_band_ap(ap_id: str, x: float, y: float) -> PhysicalApInput:
    return PhysicalApInput(
        id=ap_id,
        x=x,
        y=y,
        z=2.2,
        radios=[
            RadioInterfaceInput(
                id=f"{ap_id}-2g",
                band="2.4G",
                frequency_mhz=2437,
                tx_power_dbm=17,
            ),
            RadioInterfaceInput(
                id=f"{ap_id}-5g",
                band="5G",
                frequency_mhz=5180,
                tx_power_dbm=20,
            ),
        ],
    )


def _five_g_only_ap(ap_id: str, x: float, y: float) -> PhysicalApInput:
    return PhysicalApInput(
        id=ap_id,
        x=x,
        y=y,
        z=2.2,
        radios=[
            RadioInterfaceInput(
                id=f"{ap_id}-5g",
                band="5G",
                frequency_mhz=5180,
                tx_power_dbm=20,
            ),
        ],
    )


def test_physical_aps_take_priority_over_legacy_access_points():
    prepared = _prepare_rf_submit_from_payload(
        _payload(
            access_points=[AccessPointDTO(id="legacy", x_m=99, y_m=99, z_m=2.0)],
            physical_aps=[_dual_band_ap("ap1", 1.0, 2.0)],
        )
    )

    assert prepared is not None
    assert [ap["physical_ap_id"] for ap in prepared["access_points"]] == ["ap1"]
    assert prepared["access_points"][0]["x_m"] == pytest.approx(1.0)
    assert prepared["access_points"][0]["y_m"] == pytest.approx(2.0)
    assert prepared["access_points"][0]["radio_id"] == "ap1-5g"
    assert prepared["metadata"]["physical_aps_snapshot"][0]["id"] == "ap1"


def test_legacy_access_points_fall_back_to_existing_submit_payload():
    prepared = _prepare_rf_submit_from_payload(
        _payload(
            access_points=[AccessPointDTO(id="legacy", x_m=3.0, y_m=4.0, z_m=2.0)],
        )
    )

    assert prepared is None

    prepared = _prepare_rf_submit_from_payload(
        _payload(
            access_points=[AccessPointDTO(id="legacy", x_m=3.0, y_m=4.0, z_m=2.0)],
            simulation={},
        )
    )

    assert prepared is not None
    assert prepared["access_points"] == [{"id": "legacy", "x_m": 3.0, "y_m": 4.0, "z_m": 2.0}]
    assert prepared["metadata"]["physical_aps_snapshot"][0]["id"] == "legacy"
    assert prepared["metadata"]["band_metadata"]["band_aware_status"] == "legacy_single_band"


def test_dual_band_grouping_uses_parent_physical_ap_coordinates():
    physical_aps = [_dual_band_ap("ap1", 1.0, 2.0), _dual_band_ap("ap2", 3.0, 4.0)]

    grouped = group_radios_by_band(physical_aps)

    assert len(grouped["5G"]) == 2
    assert len(grouped["2.4G"]) == 2
    assert [(tx.x, tx.y, tx.z) for tx in grouped["5G"]] == [(1.0, 2.0, 2.2), (3.0, 4.0, 2.2)]
    assert [(tx.x, tx.y, tx.z) for tx in grouped["2.4G"]] == [(1.0, 2.0, 2.2), (3.0, 4.0, 2.2)]


def test_band_simulation_uses_leading_band_only_metadata():
    prepared = _prepare_rf_submit_from_payload(
        _payload(
            physical_aps=[_dual_band_ap("ap1", 1.0, 2.0), _dual_band_ap("ap2", 3.0, 4.0)],
            band_simulation=BandSimulationParams(
                bands=["5G", "2.4G"],
                combine_policy="prefer_5g_then_2g",
            ),
        )
    )

    band_meta = prepared["metadata"]["band_metadata"]
    assert band_meta["requested_bands"] == ["5G", "2.4G"]
    assert band_meta["executed_bands"] == ["5G"]
    assert band_meta["leading_band"] == "5G"
    assert band_meta["band_aware_status"] == "leading_band_only"
    assert "child jobs" in band_meta["todo"]


def test_coverage_semantics_are_recorded():
    prepared = _prepare_rf_submit_from_payload(
        _payload(physical_aps=[_dual_band_ap("ap1", 1.0, 2.0)])
    )

    semantics = prepared["metadata"]["coverage_semantics"]
    assert semantics["rssi_is_not_summed"] is True
    assert semantics["multi_ap_rssi_merge"] == "max_per_cell"


def test_single_requested_band_without_radios_is_validation_error():
    with pytest.raises(AppError):
        _prepare_rf_submit_from_payload(
            _payload(
                physical_aps=[_five_g_only_ap("ap1", 1.0, 2.0)],
                band_simulation=BandSimulationParams(bands=["2.4G"]),
            )
        )
