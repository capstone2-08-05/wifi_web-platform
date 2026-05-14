from __future__ import annotations

from enum import StrEnum


class AssetType(StrEnum):
    FLOORPLAN_IMAGE = "floorplan_image"


class JobStatus(StrEnum):
    """Job row 의 내부(canonical) status. DB 에 저장되는 값."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ApiJobStatus(StrEnum):
    """API 응답으로 노출하는 status. 프론트가 기대하는 값."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# 내부 status → API status normalize 맵.
# 도면 분석(floorplan_analyze)·RF(rf_simulate)·legacy(rf_run) 가 제각각 쓰는
# 종료 상태 표기를 API 경계에서 한 가지로 통일한다.
#   done / completed       → succeeded
#   queued                 → pending
#   running / failed       → 그대로
_JOB_STATUS_API_MAP: dict[str, str] = {
    JobStatus.QUEUED.value: ApiJobStatus.PENDING.value,
    JobStatus.RUNNING.value: ApiJobStatus.RUNNING.value,
    JobStatus.DONE.value: ApiJobStatus.SUCCEEDED.value,
    JobStatus.FAILED.value: ApiJobStatus.FAILED.value,
    "completed": ApiJobStatus.SUCCEEDED.value,  # legacy rf_run
    "pending": ApiJobStatus.PENDING.value,
    "succeeded": ApiJobStatus.SUCCEEDED.value,  # 이미 normalize 된 값도 통과
}


def normalize_job_status(raw: str | None) -> str:
    """내부 Job status → API 노출용 status. 모르는 값은 그대로 통과."""
    if raw is None:
        return ApiJobStatus.PENDING.value
    return _JOB_STATUS_API_MAP.get(raw, raw)
