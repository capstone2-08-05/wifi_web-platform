from __future__ import annotations

import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(backend_dir))

from app.services.rf.band_quality import (
    combine_band_maps,
    compute_band_quality_summary,
    compute_bottom_percentile,
    compute_coverage_ratio,
    rssi_to_quality_score,
)


def test_prefer_5g_then_2g_uses_2g_only_below_threshold():
    combined = combine_band_maps(
        [[-62.0, -75.0]],
        [[-58.0, -64.0]],
        "prefer_5g_then_2g",
        threshold_5g_dbm=-70.0,
    )

    assert combined == [[-62.0, -64.0]]


def test_max_policy_selects_stronger_rssi_without_summing_dbm():
    combined = combine_band_maps([[-65.0, -80.0]], [[-67.0, -60.0]], "max")

    assert combined == [[-65.0, -60.0]]


def test_weighted_policy_combines_quality_not_raw_dbm_sum():
    combined = combine_band_maps([[-45.0]], [[-90.0]], "weighted", weight_5g=0.5, weight_2g=0.5)

    assert combined[0][0] == pytest.approx(-67.5)


def test_quality_helpers_compute_coverage_and_bottom_percentile():
    rssi_map = [[-60.0, -68.0], [-72.0, -50.0]]

    assert compute_coverage_ratio(rssi_map, -67.0) == pytest.approx(0.5)
    assert compute_bottom_percentile(rssi_map, 10) == pytest.approx(-72.0)
    assert rssi_to_quality_score(-90.0) == 0.0
    assert rssi_to_quality_score(-45.0) == 1.0


def test_band_quality_summary_includes_overall_policy_metadata():
    summary = compute_band_quality_summary(
        [[-62.0, -75.0]],
        [[-58.0, -64.0]],
        [[-62.0, -64.0]],
        combine_policy="prefer_5g_then_2g",
    )

    assert summary["5G"]["coverage_ratio"] == pytest.approx(0.5)
    assert summary["2.4G"]["coverage_ratio"] == pytest.approx(1.0)
    assert summary["overall"]["combine_policy"] == "prefer_5g_then_2g"
