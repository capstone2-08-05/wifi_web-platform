"""Job 조회"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.job import Job
from app.models.project import Project
from app.models.user import User
from app.schemas.job import JobResponse
from app.schemas.pagination import PaginatedResponse


def get_job(db: Session, job_id: UUID, user: User) -> JobResponse:
    stmt = (
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(
            Job.id == str(job_id),
            Project.owner_user_id == user.id,
        )
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise AppError(
            ErrorCode.JOB_NOT_FOUND,
            "Job not found.",
            status_code=404,
        )
    return JobResponse.model_validate(job, from_attributes=True)


def list_jobs(
    db: Session,
    user: User,
    page: int,
    page_size: int,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
) -> PaginatedResponse[JobResponse]:
    base = (
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(Project.owner_user_id == user.id)
    )
    if job_type is not None:
        base = base.where(Job.job_type == job_type)
    if status is not None:
        base = base.where(Job.status == status)

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = (
        db.execute(
            base.order_by(Job.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    return PaginatedResponse[JobResponse](
        items=[JobResponse.model_validate(j, from_attributes=True) for j in rows],
        page=page,
        page_size=page_size,
        total=total,
    )
