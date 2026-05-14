"""백그라운드 Job 폴링 워커.

FastAPI lifespan 이벤트에서 asyncio.create_task 로 띄움. 주기적으로:
  1. status="running" 인 job 들을 DB 에서 조회
  2. job_type 별로 적절한 poll 함수 호출 (floorplan_analyze / rf_simulate)
  3. S3 에 결과가 도착했으면 자동으로 done/failed 처리

→ 프론트가 폴링 안 해도 백엔드가 알아서 상태 갱신.
프론트 GET 은 여전히 polling 역할 가능 (즉시 결과 보고 싶을 때).

설정:
  - JOB_POLLER_INTERVAL_SECONDS (기본 30)
  - JOB_POLLER_ENABLED (기본 true)

운영 고려사항:
  - 단일 프로세스 가정 (분산 worker 미지원 — Lock 없음).
  - 폴링 중 에러는 swallow + log. 다음 사이클에서 재시도.
  - "running" 이 오래된 job 도 같은 처리 (timeout 정책은 별도 이슈).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Job, Project, User

logger = logging.getLogger(__name__)

JOB_POLLER_INTERVAL_SECONDS = float(os.getenv("JOB_POLLER_INTERVAL_SECONDS", "30"))
JOB_POLLER_ENABLED = os.getenv("JOB_POLLER_ENABLED", "true").lower() in {"1", "true", "yes"}


async def run_job_poller_forever() -> None:
    """무한 루프 — 주기적으로 모든 running Job 한 번씩 poll."""
    if not JOB_POLLER_ENABLED:
        logger.info("Job poller disabled (JOB_POLLER_ENABLED=false)")
        return

    logger.info(
        "Job poller started, interval=%.1fs",
        JOB_POLLER_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _poll_once()
        except asyncio.CancelledError:
            logger.info("Job poller cancelled")
            raise
        except Exception:
            logger.exception("Job poller iteration failed")

        try:
            await asyncio.sleep(JOB_POLLER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("Job poller cancelled (during sleep)")
            raise


async def _poll_once() -> None:
    """한 사이클: running job 모두 조회 + 각 job 의 owner 권한으로 poll 호출."""
    # 임포트는 lazy — 순환 import 회피
    from app.services.floorplan_job_service import (
        JOB_TYPE_FLOORPLAN_ANALYZE,
        poll_floorplan_job,
    )
    from app.services.rf_job_service import JOB_TYPE_RF_SIMULATE, poll_rf_job

    # 짧게 한 번 DB 열어 running job list + owner 매핑만 추출
    db: Session = SessionLocal()
    try:
        rows = db.execute(
            select(Job.id, Job.job_type, Project.owner_user_id)
            .join(Project, Job.project_id == Project.id)
            .where(
                Job.status == "running",
                Job.job_type.in_([JOB_TYPE_FLOORPLAN_ANALYZE, JOB_TYPE_RF_SIMULATE]),
            )
        ).all()
    finally:
        db.close()

    if not rows:
        return

    logger.info("Job poller: %d running job(s) to check", len(rows))

    for job_id, job_type, owner_user_id in rows:
        await _poll_single(
            job_id=str(job_id),
            job_type=job_type,
            owner_user_id=str(owner_user_id),
            floorplan_poll=poll_floorplan_job,
            rf_poll=poll_rf_job,
        )


async def _poll_single(
    *,
    job_id: str,
    job_type: str,
    owner_user_id: str,
    floorplan_poll: Any,
    rf_poll: Any,
) -> None:
    """단일 Job 폴링. 각 호출마다 새 세션. 권한 체크용 owner User 객체 재구성."""
    db: Session = SessionLocal()
    try:
        owner = db.get(User, owner_user_id)
        if owner is None:
            logger.warning("Job %s: owner user %s not found, skip", job_id, owner_user_id)
            return

        if job_type == "floorplan_analyze":
            await floorplan_poll(db, job_id=job_id, current_user=owner)
        elif job_type == "rf_simulate":
            await rf_poll(db, job_id=job_id, current_user=owner)
        else:
            logger.warning("Job %s: unknown job_type=%s, skip", job_id, job_type)
    except Exception:
        # 개별 Job 폴링 실패는 다른 Job 폴링에 영향 주지 않게 swallow.
        logger.exception("Job poller: failed to poll job_id=%s type=%s", job_id, job_type)
    finally:
        db.close()


@contextlib.asynccontextmanager
async def job_poller_lifespan(_app: Any):
    """FastAPI lifespan: startup 시 polling task 띄움, shutdown 시 cancel."""
    task: asyncio.Task | None = None
    if JOB_POLLER_ENABLED:
        task = asyncio.create_task(run_job_poller_forever(), name="job-poller")
    try:
        yield
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
