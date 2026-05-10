"""RF Run 큐 등록 + 조회"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.job import Job
from app.models.project import Project
from app.models.rf_map import RfMap
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.rf_map import RfMapResponse
from app.schemas.rf_run import RfRunCreate, RfRunCreatedResponse, RfRunResponse


def _get_owned_scene_version(
    db: Session, scene_version_id: UUID, user: User
) -> SceneVersion:
    stmt = (
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(scene_version_id),
            Project.owner_user_id == user.id,
        )
    )
    sv = db.execute(stmt).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            status_code=404,
        )
    return sv


def _get_owned_rf_run(db: Session, rf_run_id: UUID, user: User) -> RfRun:
    stmt = (
        select(RfRun)
        .join(Project, RfRun.project_id == Project.id)
        .where(
            RfRun.id == str(rf_run_id),
            Project.owner_user_id == user.id,
        )
    )
    rr = db.execute(stmt).scalar_one_or_none()
    if rr is None:
        raise AppError(
            ErrorCode.RF_RUN_NOT_FOUND,
            "RF run not found.",
            status_code=404,
        )
    return rr


def _to_response(rr: RfRun) -> RfRunResponse:
    return RfRunResponse(
        id=rr.id,
        project_id=rr.project_id,
        floor_id=rr.floor_id,
        scene_version_id=rr.scene_version_id,
        run_type=rr.run_type,
        status=rr.status,
        request_json=rr.request_json or {},
        metrics_json=rr.metrics_json or {},
        created_at=rr.created_at,
    )


def create_rf_run(
    db: Session, payload: RfRunCreate, user: User
) -> RfRunCreatedResponse:
    sv = _get_owned_scene_version(db, payload.scene_version_id, user)

    rf_run = RfRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        request_json=payload.request_json or {},
        status="queued",
    )
    if payload.run_type is not None:
        rf_run.run_type = payload.run_type
    db.add(rf_run)
    db.flush()

    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type="rf_run",
        status="queued",
        input_json={
            "rf_run_id": rf_run.id,
            "scene_version_id": sv.id,
            "request": payload.request_json or {},
        },
    )
    db.add(job)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(rf_run)
    db.refresh(job)

    summary = _to_response(rf_run)
    return RfRunCreatedResponse(**summary.model_dump(), job_id=job.id)


def get_rf_run(db: Session, rf_run_id: UUID, user: User) -> RfRunResponse:
    return _to_response(_get_owned_rf_run(db, rf_run_id, user))


def list_maps(
    db: Session, rf_run_id: UUID, user: User
) -> list[RfMapResponse]:
    rr = _get_owned_rf_run(db, rf_run_id, user)
    rows = (
        db.execute(
            select(RfMap)
            .where(RfMap.rf_run_id == rr.id)
            .order_by(RfMap.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [RfMapResponse.model_validate(m, from_attributes=True) for m in rows]
