"""Helpers for RF obstacles derived from scene objects."""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from app.core.geom import wkb_to_geojson

DEFAULT_COLUMN_SIZE_M = 0.6
MIN_COLUMN_SIZE_M = 0.05

MATERIAL_ALIASES: dict[str, str] = {
    "drywall": "plasterboard",
    "plywood": "wood",
    "marble": "concrete",
    "glass": "glass",
    "wood": "wood",
    "concrete": "concrete",
    "plastic": "plastic",
    "\uc720\ub9ac": "glass",
    "\ub098\ubb34": "wood",
    "\ucf58\ud06c\ub9ac\ud2b8": "concrete",
    "\ud50c\ub77c\uc2a4\ud2f1": "plastic",
}


def normalize_rf_material(value: str | None, default: str | None = None) -> str | None:
    if not value:
        return default
    key = str(value).strip().lower()
    if key.startswith("itu_"):
        key = key[len("itu_"):]
    return MATERIAL_ALIASES.get(key, key) or default


def column_wall_segments(obj: Any) -> list[dict[str, float | str | None]]:
    """Return perimeter wall-like segments for a column SceneObject/DraftObject.

    The path-loss model only knows line obstacles. A rectangular column is
    represented as four short perimeter segments; each segment uses half the
    column width as thickness so a typical through-column path approximates a
    single solid obstacle instead of counting full thickness twice.
    """
    if getattr(obj, "object_type", None) != "column":
        return []

    point = _extract_point(getattr(obj, "point_geom", None))
    if point is None:
        return []
    cx, cy = point

    raw_meta_json = getattr(obj, "metadata_json", None) or {}
    meta = raw_meta_json if isinstance(raw_meta_json, dict) else {}
    width = _positive_float(meta.get("width_m"), DEFAULT_COLUMN_SIZE_M)
    height = _positive_float(meta.get("height_m"), DEFAULT_COLUMN_SIZE_M)
    half_w = width / 2.0
    half_h = height / 2.0
    if half_w <= 0 or half_h <= 0:
        return []

    raw_meta = meta.get("raw") if isinstance(meta.get("raw"), dict) else {}
    raw_material = meta.get("material_label") or meta.get("material") or raw_meta.get("material")
    material = normalize_rf_material(str(raw_material) if raw_material else None, "concrete")
    thickness = max(min(width, height) / 2.0, MIN_COLUMN_SIZE_M)

    x0, x1 = cx - half_w, cx + half_w
    y0, y1 = cy - half_h, cy + half_h
    return [
        {"x1": x0, "y1": y0, "x2": x1, "y2": y0, "thickness_m": thickness, "material": material},
        {"x1": x1, "y1": y0, "x2": x1, "y2": y1, "thickness_m": thickness, "material": material},
        {"x1": x1, "y1": y1, "x2": x0, "y2": y1, "thickness_m": thickness, "material": material},
        {"x1": x0, "y1": y1, "x2": x0, "y2": y0, "thickness_m": thickness, "material": material},
    ]


def column_wall_segments_for_objects(objects: Iterable[Any]) -> list[dict[str, float | str | None]]:
    out: list[dict[str, float | str | None]] = []
    for obj in objects:
        out.extend(column_wall_segments(obj))
    return out


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    if parsed < MIN_COLUMN_SIZE_M:
        return default
    return parsed


def _extract_point(geom: Any) -> tuple[float, float] | None:
    gj = wkb_to_geojson(geom)
    if not gj or gj.get("type") != "Point":
        return None
    coords = gj.get("coordinates") or []
    if len(coords) < 2:
        return None
    return float(coords[0]), float(coords[1])
