"""§11 Calibration: 실행 / 조회 / 파라미터 변경 이력 / 시스템 갱신"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.calibration_run import CalibrationRun
from app.models.job import Job
from app.models.measurement_session import MeasurementSession
from app.models.parameter_update import ParameterUpdate
from app.models.project import Project
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.calibration_run import (
    CalibrationRunCreate,
    CalibrationRunResponse,
    CalibrationRunUpdate,
    ParameterUpdateCreate,
    ParameterUpdateResponse,
)


JOB_TYPE_CALIBRATION = "calibration"
ALLOWED_CALIBRATION_STATUS = {"queued", "running", "completed", "failed"}


# ---------------------------------------------------------------------------
# 권한 + 검증
# ---------------------------------------------------------------------------
def _get_owned_scene_version(
    db: Session, version_id: UUID, user: User
) -> SceneVersion:
    sv = db.execute(
        select(SceneVersion)
        .join(Project, SceneVersion.project_id == Project.id)
        .where(
            SceneVersion.id == str(version_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if sv is None:
        raise AppError(
            ErrorCode.SCENE_VERSION_NOT_FOUND,
            "Scene version not found.",
            status_code=404,
        )
    return sv


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


def _get_owned_session(
    db: Session, session_id: UUID, user: User
) -> MeasurementSession:
    s = db.execute(
        select(MeasurementSession)
        .join(Project, MeasurementSession.project_id == Project.id)
        .where(
            MeasurementSession.id == str(session_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if s is None:
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_NOT_FOUND,
            "Measurement session not found.",
            status_code=404,
        )
    return s


def _get_owned_calibration_run(
    db: Session, run_id: UUID, user: User
) -> CalibrationRun:
    cr = db.execute(
        select(CalibrationRun)
        .join(Project, CalibrationRun.project_id == Project.id)
        .where(
            CalibrationRun.id == str(run_id),
            Project.owner_user_id == user.id,
        )
    ).scalar_one_or_none()
    if cr is None:
        raise AppError(
            ErrorCode.CALIBRATION_RUN_NOT_FOUND,
            "Calibration run not found.",
            status_code=404,
        )
    return cr


def _get_calibration_run_or_404(db: Session, run_id: UUID) -> CalibrationRun:
    """[시스템 호출용] owner 체크 없이 단순 조회."""
    cr = db.execute(
        select(CalibrationRun).where(CalibrationRun.id == str(run_id))
    ).scalar_one_or_none()
    if cr is None:
        raise AppError(
            ErrorCode.CALIBRATION_RUN_NOT_FOUND,
            "Calibration run not found.",
            status_code=404,
        )
    return cr


# ---------------------------------------------------------------------------
# alias 매핑 (모델 → 명세 응답)
# ---------------------------------------------------------------------------
def _to_response(cr: CalibrationRun) -> CalibrationRunResponse:
    metrics = cr.metrics_json or {}
    # error_heatmap_url 은 명세상 top-level. 모델엔 별도 컬럼이 없어 metrics_json 안에 담는 규약.
    heatmap_url = metrics.get("error_heatmap_url")
    return CalibrationRunResponse(
        id=cr.id,
        status=cr.status,
        session_id=cr.measurement_session_id,
        rf_run_id=cr.rf_run_id,
        version_id=cr.scene_version_id,
        error_metrics_json=metrics,
        error_heatmap_url=heatmap_url,
        created_at=cr.created_at,
        finished_at=cr.finished_at,
    )


def _pu_to_response(pu: ParameterUpdate) -> ParameterUpdateResponse:
    return ParameterUpdateResponse(
        id=pu.id,
        calibration_run_id=pu.calibration_run_id,
        target_type=pu.target_type,
        target_id=pu.target_id,
        param_name=pu.parameter_name,
        old_value_json=pu.old_value_json,
        new_value_json=pu.new_value_json,
        created_at=pu.created_at,
    )


# ---------------------------------------------------------------------------
# §11.1 실행
# ---------------------------------------------------------------------------
def create_calibration_run(
    db: Session, payload: CalibrationRunCreate, user: User
) -> CalibrationRunResponse:
    sv = _get_owned_scene_version(db, payload.version_id, user)
    rr = _get_owned_rf_run(db, payload.rf_run_id, user)
    ms = _get_owned_session(db, payload.session_id, user)

    # 동일 floor 에 속해야 의미있는 비교. 다르면 거부.
    if not (sv.floor_id == rr.floor_id == ms.floor_id):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            "scene_version / rf_run / measurement_session must belong to the same floor.",
            status_code=400,
        )

    cr = CalibrationRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        rf_run_id=rr.id,
        measurement_session_id=ms.id,
        status="queued",
    )
    db.add(cr)
    db.flush()

    # AI 워커 등록용 Job. 워커가 아직 없어도 큐에 쌓임 (poller 가 type 모르면 skip).
    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type=JOB_TYPE_CALIBRATION,
        status="queued",
        input_json={
            "calibration_run_id": cr.id,
            "scene_version_id": sv.id,
            "rf_run_id": rr.id,
            "measurement_session_id": ms.id,
        },
    )
    db.add(job)

    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise
    return _to_response(cr)


# ---------------------------------------------------------------------------
# §11.2 결과 조회
# ---------------------------------------------------------------------------
def get_calibration_run(
    db: Session, run_id: UUID, user: User
) -> CalibrationRunResponse:
    return _to_response(_get_owned_calibration_run(db, run_id, user))


# ---------------------------------------------------------------------------
# §11.3 파라미터 변경 이력
# ---------------------------------------------------------------------------
def list_parameter_updates(
    db: Session, run_id: UUID, user: User
) -> list[ParameterUpdateResponse]:
    cr = _get_owned_calibration_run(db, run_id, user)
    rows = (
        db.execute(
            select(ParameterUpdate)
            .where(ParameterUpdate.calibration_run_id == cr.id)
            .order_by(ParameterUpdate.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [_pu_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# 시스템 호출 (AI 워커 → 백엔드)
# ---------------------------------------------------------------------------
def _find_associated_job(db: Session, calibration_run_id: str) -> Job | None:
    return db.execute(
        select(Job).where(
            Job.job_type == JOB_TYPE_CALIBRATION,
            Job.input_json["calibration_run_id"].astext == calibration_run_id,
        )
    ).scalar_one_or_none()


def update_calibration_run(
    db: Session, run_id: UUID, payload: CalibrationRunUpdate
) -> CalibrationRunResponse:
    cr = _get_calibration_run_or_404(db, run_id)
    data = payload.model_dump(exclude_unset=True)

    new_status = data.get("status")
    if new_status is not None and new_status not in ALLOWED_CALIBRATION_STATUS:
        raise AppError(
            ErrorCode.INVALID_CALIBRATION_STATUS,
            f"Invalid status: {new_status}. Allowed: {sorted(ALLOWED_CALIBRATION_STATUS)}",
            status_code=400,
        )

    now = datetime.now(timezone.utc)
    if new_status is not None:
        cr.status = new_status
        if new_status in {"completed", "failed"} and cr.finished_at is None:
            cr.finished_at = now
    if "metrics_json" in data and data["metrics_json"] is not None:
        cr.metrics_json = data["metrics_json"]
    if "error_message" in data:
        cr.error_message = data["error_message"]

    job = _find_associated_job(db, cr.id)
    if job is not None:
        if new_status is not None:
            job.status = new_status
            if new_status == "running" and job.started_at is None:
                job.started_at = now
            if new_status in {"completed", "failed"}:
                job.finished_at = now
        if "error_message" in data:
            job.error_message = data["error_message"]

    try:
        db.commit()
        db.refresh(cr)
    except Exception:
        db.rollback()
        raise
    return _to_response(cr)


def create_parameter_update(
    db: Session, run_id: UUID, payload: ParameterUpdateCreate
) -> ParameterUpdateResponse:
    cr = _get_calibration_run_or_404(db, run_id)
    pu = ParameterUpdate(
        calibration_run_id=cr.id,
        target_type=payload.target_type,
        target_id=str(payload.target_id),
        parameter_name=payload.param_name,
        old_value_json=payload.old_value_json,
        new_value_json=payload.new_value_json,
    )
    db.add(pu)
    try:
        db.commit()
        db.refresh(pu)
    except Exception:
        db.rollback()
        raise
    return _pu_to_response(pu)
