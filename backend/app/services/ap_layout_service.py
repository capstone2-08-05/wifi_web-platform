"""AP Layout CRUD (§14.3, §14.4)"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.geom import geojson_to_wkb, wkb_to_geojson
from app.models.ap_layout import ApLayout
from app.models.project import Project
from app.models.rf_run import RfRun
from app.models.user import User
from app.schemas.ap_layout import (
    ApLayoutCreate,
    ApLayoutResponse,
    ApLayoutUpdate,
)


def _to_response(layout: ApLayout) -> ApLayoutResponse:
    return ApLayoutResponse(
        id=layout.id,
        rf_run_id=layout.rf_run_id,
        ap_name=layout.ap_name,
        vendor_model=layout.vendor_model,
        point_geom=wkb_to_geojson(layout.point_geom),
        z_m=layout.z_m,
        azimuth_deg=layout.azimuth_deg,
        tilt_deg=layout.tilt_deg,
        power_dbm=layout.power_dbm,
        channel_info_json=layout.channel_info_json or {},
        created_at=layout.created_at,
        updated_at=layout.updated_at,
    )


def _get_owned_rf_run(db: Session, rf_run_id: UUID, user: User) -> RfRun:
    rr = db.execute(
        select(RfRun)
        .join(Project, RfRun.project_id == Project.id)
        .where(
            RfRun.id == str(rf_run_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if rr is None:
        raise AppError(
            ErrorCode.RF_RUN_NOT_FOUND,
            "RF run not found.",
            status_code=404,
        )
    return rr


def _get_owned_layout(db: Session, layout_id: UUID, user: User) -> ApLayout:
    layout = db.execute(
        select(ApLayout)
        .join(RfRun, ApLayout.rf_run_id == RfRun.id)
        .join(Project, RfRun.project_id == Project.id)
        .where(
            ApLayout.id == str(layout_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if layout is None:
        raise AppError(
            ErrorCode.AP_LAYOUT_NOT_FOUND,
            "AP layout not found.",
            status_code=404,
        )
    return layout


def list_by_rf_run(
    db: Session, rf_run_id: UUID, user: User
) -> list[ApLayoutResponse]:
    rr = _get_owned_rf_run(db, rf_run_id, user)
    rows = (
        db.execute(
            select(ApLayout)
            .where(ApLayout.rf_run_id == rr.id)
            .order_by(ApLayout.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [_to_response(r) for r in rows]


def get_layout(db: Session, layout_id: UUID, user: User) -> ApLayoutResponse:
    return _to_response(_get_owned_layout(db, layout_id, user))


def create_layout(
    db: Session, payload: ApLayoutCreate, user: User
) -> ApLayoutResponse:
    rr = _get_owned_rf_run(db, payload.rf_run_id, user)

    layout = ApLayout(
        rf_run_id=rr.id,
        ap_name=payload.ap_name,
        vendor_model=payload.vendor_model,
        point_geom=geojson_to_wkb(payload.point_geom, "Point", "point_geom"),
        z_m=payload.z_m,
        azimuth_deg=payload.azimuth_deg,
        tilt_deg=payload.tilt_deg,
        power_dbm=payload.power_dbm,
        channel_info_json=payload.channel_info_json or {},
    )
    db.add(layout)
    try:
        db.commit()
        db.refresh(layout)
    except Exception:
        db.rollback()
        raise
    return _to_response(layout)


def update_layout(
    db: Session, layout_id: UUID, payload: ApLayoutUpdate, user: User
) -> ApLayoutResponse:
    layout = _get_owned_layout(db, layout_id, user)
    data = payload.model_dump(exclude_unset=True)

    if "point_geom" in data and data["point_geom"] is not None:
        layout.point_geom = geojson_to_wkb(
            data["point_geom"], "Point", "point_geom"
        )
    for field in (
        "ap_name",
        "vendor_model",
        "z_m",
        "azimuth_deg",
        "tilt_deg",
        "power_dbm",
        "channel_info_json",
    ):
        if field in data:
            setattr(layout, field, data[field])

    try:
        db.commit()
        db.refresh(layout)
    except Exception:
        db.rollback()
        raise
    return _to_response(layout)


def delete_layout(db: Session, layout_id: UUID, user: User) -> None:
    layout = _get_owned_layout(db, layout_id, user)
    db.delete(layout)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
