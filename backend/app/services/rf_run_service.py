"""RF Run 큐 등록 + 조회 + 결과 저장"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.floor import Floor
from app.models.job import Job
from app.models.project import Project
from app.models.rf_map import RfMap
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.pagination import PaginatedResponse
from app.schemas.rf_map import RfMapCreate, RfMapResponse
from app.schemas.rf_run import (
    RfRunCreate,
    RfRunCreatedResponse,
    RfRunResponse,
    RfRunUpdate,
)


ALLOWED_RF_RUN_STATUS = {"queued", "running", "completed", "failed"}


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


async def create_rf_run(
    db: Session, payload: RfRunCreate, user: User
) -> RfRunCreatedResponse:
    """RF 시뮬레이션 Job 등록.

    - payload.access_points + payload.simulation 둘 다 있으면 → SageMaker async invoke 흐름
    - 둘 다 없으면 → legacy queue 등록 (deprecated, 외부 worker 가 처리하는 옛 흐름)
    """
    sv = _get_owned_scene_version(db, payload.scene_version_id, user)

    # 새 흐름: SageMaker async 호출
    if payload.access_points and payload.simulation:
        from app.services.rf_job_service import submit_rf_simulation

        rf_run, job = await submit_rf_simulation(
            db,
            scene_version_id=sv.id,
            access_points=[ap.model_dump() for ap in payload.access_points],
            simulation=payload.simulation.model_dump(),
            current_user=user,
            run_type=payload.run_type or "rf_simulate",
            metadata=payload.metadata,
            apply_calibration=payload.apply_calibration,
        )
        summary = _to_response(rf_run)
        return RfRunCreatedResponse(**summary.model_dump(), job_id=job.id)

    # Legacy 흐름 (외부 worker 가 폴링하는 큐 모델)
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


def list_by_floor(
    db: Session,
    floor_id: UUID,
    user: User,
    page: int,
    page_size: int,
    status: str | None = None,
) -> PaginatedResponse[RfRunResponse]:
    """층의 RF Run 목록 (페이지네이션 + status 필터). created_at desc."""
    # 권한: floor 소유 확인
    floor = db.execute(
        select(Floor)
        .join(Project, Floor.project_id == Project.id)
        .where(Floor.id == str(floor_id), Project.owner_user_id == user.id)
    ).scalar_one_or_none()
    if floor is None:
        raise AppError(
            ErrorCode.FLOOR_NOT_FOUND,
            "Floor not found.",
            status_code=404,
        )

    base = select(RfRun).where(RfRun.floor_id == str(floor_id))
    count_stmt = select(func.count(RfRun.id)).where(RfRun.floor_id == str(floor_id))
    if status is not None:
        base = base.where(RfRun.status == status)
        count_stmt = count_stmt.where(RfRun.status == status)

    total = db.execute(count_stmt).scalar() or 0
    rows = (
        db.execute(
            base.order_by(RfRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse[RfRunResponse](
        items=[_to_response(r) for r in rows],
        page=page,
        page_size=page_size,
        total=int(total),
    )


def _rf_map_to_response(m: RfMap) -> RfMapResponse:
    """storage_url 이 s3:// 면 presigned URL 도 같이 채워서 반환."""
    resp = RfMapResponse.model_validate(m, from_attributes=True)
    if m.storage_url and m.storage_url.startswith("s3://"):
        from app.services import _s3
        try:
            resp = resp.model_copy(update={"url": _s3.presigned_get_url(m.storage_url)})
        except Exception:
            # presigned 발급 실패 시 url=None 유지 (storage_url 은 남음)
            pass
    return resp


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
    return [_rf_map_to_response(m) for m in rows]


# ---------------------------------------------------------------------------
# 시스템 호출 (AI 서버 → 백엔드)
# ---------------------------------------------------------------------------
def _get_rf_run_or_404(db: Session, rf_run_id: UUID) -> RfRun:
    rr = db.execute(
        select(RfRun).where(RfRun.id == str(rf_run_id))
    ).scalar_one_or_none()
    if rr is None:
        raise AppError(
            ErrorCode.RF_RUN_NOT_FOUND,
            "RF run not found.",
            status_code=404,
        )
    return rr


def _find_associated_job(db: Session, rf_run_id: str) -> Job | None:
    """input_json.rf_run_id 로 연관된 jobs row 1건 찾음."""
    return db.execute(
        select(Job).where(
            Job.job_type == "rf_run",
            Job.input_json["rf_run_id"].astext == rf_run_id,
        )
    ).scalar_one_or_none()


def update_rf_run(
    db: Session, rf_run_id: UUID, payload: RfRunUpdate
) -> RfRunResponse:
    rr = _get_rf_run_or_404(db, rf_run_id)
    data = payload.model_dump(exclude_unset=True)

    new_status = data.get("status")
    if new_status is not None and new_status not in ALLOWED_RF_RUN_STATUS:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"Invalid status: {new_status}. Allowed: {sorted(ALLOWED_RF_RUN_STATUS)}",
            status_code=400,
        )

    if new_status is not None:
        rr.status = new_status
    if "metrics_json" in data and data["metrics_json"] is not None:
        rr.metrics_json = data["metrics_json"]

    job = _find_associated_job(db, rr.id)
    if job is not None:
        now = datetime.now(timezone.utc)
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
        db.refresh(rr)
    except Exception:
        db.rollback()
        raise
    return _to_response(rr)


def create_rf_map(
    db: Session, rf_run_id: UUID, payload: RfMapCreate
) -> RfMapResponse:
    rr = _get_rf_run_or_404(db, rf_run_id)
    rf_map = RfMap(
        rf_run_id=rr.id,
        map_type=payload.map_type,
        resolution_cm=payload.resolution_cm,
        storage_url=payload.storage_url,
        bounds_json=payload.bounds_json or {},
        metrics_json=payload.metrics_json or {},
    )
    try:
        db.add(rf_map)
        db.commit()
        db.refresh(rf_map)
    except Exception:
        db.rollback()
        raise
    return _rf_map_to_response(rf_map)
