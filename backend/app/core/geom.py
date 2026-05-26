"""GeoJSON <-> PostGIS geometry 변환 헬퍼"""
from __future__ import annotations

from typing import Any, Optional

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.errors import GEOSException, ShapelyError
from shapely.geometry import mapping, shape

from app.core.errors import AppError, ErrorCode


def geojson_to_wkb(
    geojson: Optional[dict[str, Any]],
    expected_type: str,
    field_name: str,
) -> Optional[WKBElement]:
    if geojson is None:
        return None
    try:
        geom = shape(geojson)
    except (ShapelyError, GEOSException, ValueError, TypeError, KeyError) as exc:
        raise AppError(
            ErrorCode.INVALID_GEOMETRY,
            f"Invalid GeoJSON for {field_name}: {exc}",
            status_code=400,
        ) from exc
    if geom.geom_type != expected_type:
        raise AppError(
            ErrorCode.INVALID_GEOMETRY,
            f"{field_name} must be a {expected_type}, got {geom.geom_type}",
            status_code=400,
        )
    return from_shape(geom, srid=0)


def wkb_to_geojson(geom: Any) -> Optional[dict[str, Any]]:
    if geom is None:
        return None
    return mapping(to_shape(geom))


def scale_wkb(geom: Any, factor: float) -> Optional[WKBElement]:
    """SceneDraft 전체 비례 재스케일용 — geometry 좌표 × factor (origin=0,0).

    좌표 origin 이 도면 top-left 라 (0,0) 기준 곱셈만으로 충분.
    NULL 통과 (요청 못 받는 컬럼도 안전).
    """
    if geom is None:
        return None
    from shapely.affinity import scale as shapely_scale
    shp = to_shape(geom)
    scaled = shapely_scale(shp, xfact=factor, yfact=factor, origin=(0, 0))
    return from_shape(scaled, srid=0)
