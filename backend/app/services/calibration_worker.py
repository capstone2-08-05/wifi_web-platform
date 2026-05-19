"""§11 캘리브레이션 백그라운드 워커 (스켈레톤).

`job_poller` 가 `JOB_TYPE_CALIBRATION` 인 Job (status=running) 을 매 사이클
픽업해서 호출. 같은 프로세스 안이므로 HTTP/internal key 없이 service 함수 직접 호출.

**현재는 스켈레톤**: 측정 데이터 기본 통계 계산 + completed 마킹까지.
진짜 보정 알고리즘은 RF 시뮬 결과 (RfMap heatmap) 가 들어오기 시작하면
`_compute_real_error_metrics` 를 채우는 식으로 확장.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.calibration_run import CalibrationRun
from app.models.job import Job
from app.models.measurement_point import MeasurementPoint
from app.models.user import User


logger = logging.getLogger(__name__)

JOB_TYPE_CALIBRATION = "calibration"


def _fail(db: Session, cr: CalibrationRun, job: Job | None, message: str) -> None:
    now = datetime.now(timezone.utc)
    cr.status = "failed"
    cr.error_message = message
    cr.finished_at = now
    if job is not None:
        job.status = "failed"
        job.error_message = message
        job.finished_at = now
    db.commit()
    logger.warning("Calibration %s failed: %s", cr.id, message)


def _summarize_measurements(points: list[MeasurementPoint]) -> dict[str, Any]:
    """RSSI 값이 있는 측정 지점만 모아서 간단 통계."""
    rssi_values: list[float] = []
    for p in points:
        if p.rssi_dbm is None:
            continue
        rssi_values.append(float(p.rssi_dbm))
    if not rssi_values:
        return {"point_count": len(points), "rssi_count": 0}
    return {
        "point_count": len(points),
        "rssi_count": len(rssi_values),
        "rssi_mean_dbm": round(sum(rssi_values) / len(rssi_values), 2),
        "rssi_min_dbm": min(rssi_values),
        "rssi_max_dbm": max(rssi_values),
    }


async def poll_calibration_job(
    db: Session, *, job_id: str, current_user: User
) -> Job:
    """job_poller 가 매 사이클 호출. 같은 시그니처 (job_id, current_user)."""
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
    if job is None:
        logger.warning("Calibration job %s not found", job_id)
        return None  # type: ignore[return-value]
    if job.status != "running":
        # 이미 다른 사이클에서 완료 처리됨 — idempotent.
        return job

    calibration_run_id = (job.input_json or {}).get("calibration_run_id")
    if not calibration_run_id:
        _fail(db, _stub_cr(), job, "Job.input_json.calibration_run_id missing")
        return job

    cr = db.execute(
        select(CalibrationRun).where(CalibrationRun.id == calibration_run_id)
    ).scalar_one_or_none()
    if cr is None:
        job.status = "failed"
        job.error_message = "CalibrationRun not found"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return job

    # ── 1) 측정 데이터 로드 ──────────────────────────────────────────
    points = list(
        db.execute(
            select(MeasurementPoint).where(
                MeasurementPoint.session_id == cr.measurement_session_id
            )
        )
        .scalars()
        .all()
    )
    if not points:
        _fail(db, cr, job, "No measurement points found for the session.")
        return job

    # ── 2) 기본 통계 (스켈레톤 — 진짜 error metric 은 RfMap 비교 필요) ──
    stats = _summarize_measurements(points)
    cr.metrics_json = {
        **stats,
        "note": (
            "Skeleton worker: real error metrics (rmse, mae) require comparing "
            "with predicted RSSI from RfMap. Not implemented yet."
        ),
    }

    # ── 3) 완료 처리 ────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    cr.status = "completed"
    cr.finished_at = now
    job.status = "completed"
    job.finished_at = now

    try:
        db.commit()
        db.refresh(cr)
        db.refresh(job)
    except Exception:
        db.rollback()
        raise

    logger.info(
        "Calibration %s completed (skeleton): %d points, %d rssi",
        cr.id, stats.get("point_count", 0), stats.get("rssi_count", 0),
    )
    return job


def _stub_cr() -> CalibrationRun:
    """타입 체크용 더미. 실제로 _fail 호출 전에 cr 있는 경로에서만 쓰임."""
    return CalibrationRun()  # type: ignore[call-arg]
