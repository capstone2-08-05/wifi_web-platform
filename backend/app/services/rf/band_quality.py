"""Band-aware RF quality helpers.

The helpers in this module deliberately combine already-merged per-band RSSI
maps. They do not sum dBm values and they do not sum multiple AP/radio RSSI.
Callers should first reduce each band to a per-cell best RSSI map.
"""
from __future__ import annotations

import math
from typing import Any, Literal, Sequence

CombinePolicy = Literal["max", "prefer_5g_then_2g", "weighted"]


def rssi_to_quality_score(
    rssi_dbm: float | None,
    *,
    floor_dbm: float = -90.0,
    excellent_dbm: float = -45.0,
) -> float:
    """Convert RSSI dBm to a bounded 0..1 quality score."""
    if rssi_dbm is None or not math.isfinite(float(rssi_dbm)):
        return 0.0
    value = float(rssi_dbm)
    if value <= floor_dbm:
        return 0.0
    if value >= excellent_dbm:
        return 1.0
    return (value - floor_dbm) / (excellent_dbm - floor_dbm)


def quality_score_to_rssi(
    score: float,
    *,
    floor_dbm: float = -90.0,
    excellent_dbm: float = -45.0,
) -> float:
    bounded = min(1.0, max(0.0, score if math.isfinite(score) else 0.0))
    return floor_dbm + bounded * (excellent_dbm - floor_dbm)


def combine_band_maps(
    map_5g: Sequence[Sequence[float | None]] | None,
    map_2g: Sequence[Sequence[float | None]] | None,
    policy: CombinePolicy = "prefer_5g_then_2g",
    *,
    threshold_5g_dbm: float = -70.0,
    weight_5g: float = 0.7,
    weight_2g: float = 0.3,
) -> list[list[float]]:
    """Combine best-per-cell 5GHz and 2.4GHz RSSI maps into an overall map."""
    rows, cols = _common_shape(map_5g, map_2g)
    out: list[list[float]] = []
    for r in range(rows):
        row: list[float] = []
        for c in range(cols):
            v5 = _cell(map_5g, r, c)
            v2 = _cell(map_2g, r, c)
            row.append(
                combine_band_values(
                    v5,
                    v2,
                    policy,
                    threshold_5g_dbm=threshold_5g_dbm,
                    weight_5g=weight_5g,
                    weight_2g=weight_2g,
                )
            )
        out.append(row)
    return out


def combine_band_values(
    rssi_5g: float | None,
    rssi_2g: float | None,
    policy: CombinePolicy = "prefer_5g_then_2g",
    *,
    threshold_5g_dbm: float = -70.0,
    weight_5g: float = 0.7,
    weight_2g: float = 0.3,
) -> float:
    v5 = _valid_or_none(rssi_5g)
    v2 = _valid_or_none(rssi_2g)
    if v5 is None and v2 is None:
        return -110.0
    if v5 is None:
        return float(v2)
    if v2 is None:
        return float(v5)

    if policy == "max":
        return max(v5, v2)
    if policy == "weighted":
        total = max(0.0, weight_5g) + max(0.0, weight_2g)
        if total <= 0:
            return max(v5, v2)
        quality = (
            rssi_to_quality_score(v5) * max(0.0, weight_5g)
            + rssi_to_quality_score(v2) * max(0.0, weight_2g)
        ) / total
        return quality_score_to_rssi(quality)
    return v5 if v5 >= threshold_5g_dbm else v2


def compute_coverage_ratio(
    rssi_map: Sequence[Sequence[float | None]],
    threshold_dbm: float,
) -> float:
    values = _flatten_valid(rssi_map)
    if not values:
        return 0.0
    return sum(1 for value in values if value >= threshold_dbm) / len(values)


def compute_bottom_percentile(
    rssi_map: Sequence[Sequence[float | None]],
    percentile: float = 10.0,
) -> float | None:
    values = sorted(_flatten_valid(rssi_map))
    if not values:
        return None
    bounded = min(100.0, max(0.0, percentile))
    index = max(0, min(len(values) - 1, math.ceil((bounded / 100.0) * len(values)) - 1))
    return values[index]


def compute_weak_zone_ratio(
    rssi_map: Sequence[Sequence[float | None]],
    threshold_dbm: float,
) -> float:
    values = _flatten_valid(rssi_map)
    if not values:
        return 0.0
    return sum(1 for value in values if value < threshold_dbm) / len(values)


def compute_band_quality_summary(
    map_5g: Sequence[Sequence[float | None]] | None,
    map_2g: Sequence[Sequence[float | None]] | None,
    overall_map: Sequence[Sequence[float | None]],
    *,
    coverage_threshold_dbm: float = -67.0,
    weak_zone_threshold_dbm: float = -67.0,
    combine_policy: CombinePolicy = "prefer_5g_then_2g",
) -> dict[str, Any]:
    return {
        "5G": _map_summary(map_5g, coverage_threshold_dbm, weak_zone_threshold_dbm),
        "2.4G": _map_summary(map_2g, coverage_threshold_dbm, weak_zone_threshold_dbm),
        "overall": {
            **_map_summary(overall_map, coverage_threshold_dbm, weak_zone_threshold_dbm),
            "combine_policy": combine_policy,
        },
    }


def _map_summary(
    rssi_map: Sequence[Sequence[float | None]] | None,
    coverage_threshold_dbm: float,
    weak_zone_threshold_dbm: float,
) -> dict[str, Any]:
    if not rssi_map:
        return {
            "coverage_ratio": None,
            "average_rssi": None,
            "bottom_10_percent": None,
            "weak_zone_ratio": None,
        }
    values = _flatten_valid(rssi_map)
    if not values:
        return {
            "coverage_ratio": 0.0,
            "average_rssi": None,
            "bottom_10_percent": None,
            "weak_zone_ratio": 0.0,
        }
    return {
        "coverage_ratio": compute_coverage_ratio(rssi_map, coverage_threshold_dbm),
        "average_rssi": sum(values) / len(values),
        "bottom_10_percent": compute_bottom_percentile(rssi_map, 10),
        "weak_zone_ratio": compute_weak_zone_ratio(rssi_map, weak_zone_threshold_dbm),
    }


def _common_shape(*maps: Sequence[Sequence[float | None]] | None) -> tuple[int, int]:
    shapes = [
        (len(m), min((len(row) for row in m), default=0))
        for m in maps
        if m is not None and len(m) > 0
    ]
    if not shapes:
        return (0, 0)
    return min(rows for rows, _ in shapes), min(cols for _, cols in shapes)


def _cell(
    rssi_map: Sequence[Sequence[float | None]] | None,
    row: int,
    col: int,
) -> float | None:
    if rssi_map is None or row >= len(rssi_map) or col >= len(rssi_map[row]):
        return None
    return _valid_or_none(rssi_map[row][col])


def _valid_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _flatten_valid(rssi_map: Sequence[Sequence[float | None]]) -> list[float]:
    values: list[float] = []
    for row in rssi_map:
        for value in row:
            parsed = _valid_or_none(value)
            if parsed is not None:
                values.append(parsed)
    return values
