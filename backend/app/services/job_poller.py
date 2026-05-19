"""백그라운드 Job 폴링 워커.

FastAPI lifespan 이벤트에서 asyncio.create_task 로 띄움. 주기적으로:
  1. status="running" 인 job 들을 DB 에서 조회
  2. job_type 별로 적절한 poll 함수 호출 (floorplan_analyze / rf_simulate)
  3. S3 에 결과가 도착했으면 자동으로 done/failed 처리

→ 프론트가 폴링 안 해도 백엔드가 알아서 상태 갱신.
프론트 GET 은 여전히 polling 역할 가능 (즉시 결과 보고 싶을 때).

설정 (env):
  - JOB_POLLER_ENABLED          (기본 true)
  - JOB_POLLER_INTERVAL_SECONDS (기본 60)
  - JOB_POLLER_MAX_PER_CYCLE    (기본 8)  — 한 사이클에 폴링할 job 상한
  - JOB_POLLER_MAX_AGE_MINUTES  (기본 90) — 이보다 오래된 running job 은 스킵 (사실상 죽은 job)

운영 안전장치:
  - 한 사이클에 폴링하는 job 수 상한 (MAX_PER_CYCLE) — DB 커넥션 풀 압박 방지.
    오래된 job 부터 우선 처리하되, 너무 오래된(MAX_AGE) 건 아예 스킵.
  - boto3 client 는 bounded timeout (app.core.aws) — AWS 호출이 hang 해도
    DB 세션을 무한정 잡지 않음.
  - 각 job 은 자기 세션으로 폴링하고 즉시 close — 세션 수명 최소화.
  - 단일 프로세스 가정 (분산 worker 미지원 — row lock 으로 중복 finalize 만 방지).
  - 폴링 중 에러는 swallow + log. 다음 사이클에서 재시도.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Job, Project, User

logger = logging.getLogger(__name__)

JOB_POLLER_INTERVAL_SECONDS = float(os.getenv("JOB_POLLER_INTERVAL_SECONDS", "60"))
JOB_POLLER_ENABLED = os.getenv("JOB_POLLER_ENABLED", "true").lower() in {"1", "true", "yes"}
# 한 사이클에 폴링할 job 상한 — 너무 많으면 DB 세션/스레드 압박.
JOB_POLLER_MAX_PER_CYCLE = int(os.getenv("JOB_POLLER_MAX_PER_CYCLE", "8"))
# 이보다 오래된 running job 은 스킵 (SageMaker cold start 최대치를 한참 넘김 = 사실상 죽음).
JOB_POLLER_MAX_AGE_MINUTES = int(os.getenv("JOB_POLLER_MAX_AGE_MINUTES", "90"))


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
    """한 사이클: running job 조회 → 오래된 건 스킵 → 상한만큼만 폴링."""
    # 임포트는 lazy — 순환 import 회피
    from app.services.calibration_worker import (
        JOB_TYPE_CALIBRATION,
        poll_calibration_job,
    )
    from app.services.floorplan_job_service import (
        JOB_TYPE_FLOORPLAN_ANALYZE,
        poll_floorplan_job,
    )
    from app.services.rf_job_service import JOB_TYPE_RF_SIMULATE, poll_rf_job

    now = datetime.now(timezone.utc)
    min_created = now - timedelta(minutes=JOB_POLLER_MAX_AGE_MINUTES)

    # 짧게 한 번 DB 열어 running job list 만 추출.
    # 오래된 죽은 job 은 제외, 오래된 순으로 정렬해 상한만큼만 (오래 기다린 게 우선).
    db: Session = SessionLocal()
    try:
        rows = db.execute(
            select(Job.id, Job.job_type, Project.owner_user_id)
            .join(Project, Job.project_id == Project.id)
            .where(
                Job.status == "running",
                Job.job_type.in_(
                    [JOB_TYPE_FLOORPLAN_ANALYZE, JOB_TYPE_RF_SIMULATE, JOB_TYPE_CALIBRATION]
                ),
                Job.created_at >= min_created,
            )
            .order_by(Job.created_at.asc())
            .limit(JOB_POLLER_MAX_PER_CYCLE)
        ).all()
    finally:
        db.close()

    if not rows:
        return

    logger.info(
        "Job poller: polling %d running job(s) (cap=%d, max_age=%dm)",
        len(rows), JOB_POLLER_MAX_PER_CYCLE, JOB_POLLER_MAX_AGE_MINUTES,
    )

    for job_id, job_type, owner_user_id in rows:
        await _poll_single(
            job_id=str(job_id),
            job_type=job_type,
            owner_user_id=str(owner_user_id),
            floorplan_poll=poll_floorplan_job,
            rf_poll=poll_rf_job,
            calibration_poll=poll_calibration_job,
        )


async def _poll_single(
    *,
    job_id: str,
    job_type: str,
    owner_user_id: str,
    floorplan_poll: Any,
    rf_poll: Any,
    calibration_poll: Any,
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
        elif job_type == "calibration":
            await calibration_poll(db, job_id=job_id, current_user=owner)
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
