"""RF Run 큐 등록 + 조회 + 결과 저장"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
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
from app.schemas.rf.rf_map import RfMapCreate, RfMapResponse
from app.schemas.rf.rf_run import (
    BandSimulationParams,
    RfRunCreate,
    RfRunCreatedResponse,
    RfRunResponse,
    RfRunUpdate,
    RfSimulationParams,
)
from app.services.rf.physical_ap_helpers import (
    build_band_metadata,
    group_radios_by_band,
    normalize_physical_aps_from_request,
    physical_aps_to_access_point_list,
)


ALLOWED_RF_RUN_STATUS = {"queued", "running", "completed", "failed"}

COVERAGE_SEMANTICS: dict[str, Any] = {
    "multi_ap_rssi_merge": "max_per_cell",
    "rssi_is_not_summed": True,
    "recommendation_unit": "physical_ap",
}


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


def _prepare_rf_submit_from_payload(payload: RfRunCreate) -> dict[str, Any] | None:
    """Build the backend-compatible RF submit payload.

    Physical APs take priority. Legacy access_points still flow through unchanged
    unless physical_aps are present.
    """
    has_physical_aps = bool(payload.physical_aps)
    has_legacy_submit = bool(payload.access_points and payload.simulation)
    if not has_physical_aps and not has_legacy_submit:
        return None

    simulation_model = payload.simulation or RfSimulationParams()
    simulation = simulation_model.model_dump()
    legacy_aps = [ap.model_dump(mode="json") for ap in payload.access_points or []]

    if not has_physical_aps:
        legacy_physical_aps = normalize_physical_aps_from_request(
            physical_aps=None,
            existing_aps=legacy_aps,
            candidate_tx_power_dbm=float(simulation.get("tx_power_dbm") or 20.0),
        )
        metadata = {
            **(payload.metadata or {}),
            "physical_aps_snapshot": [
                ap.model_dump(mode="json") for ap in legacy_physical_aps
            ],
            "band_metadata": {
                "requested_bands": ["5G"],
                "executed_bands": ["5G"],
                "leading_band": "5G",
                "combine_policy": "prefer_5g_then_2g",
                "band_aware_status": "legacy_single_band",
                "bands": build_band_metadata(legacy_physical_aps, ["5G"]),
            },
            "coverage_semantics": COVERAGE_SEMANTICS,
            "normalization_warnings": [],
        }
        return {
            "access_points": legacy_aps,
            "simulation": simulation,
            "metadata": metadata,
        }

    fallback_tx_power_dbm = float(simulation.get("tx_power_dbm") or 20.0)
    physical_aps = normalize_physical_aps_from_request(
        physical_aps=payload.physical_aps or None,
        existing_aps=legacy_aps,
        candidate_tx_power_dbm=fallback_tx_power_dbm,
    )
    if not physical_aps:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            "RF run requires at least one physical AP or legacy access point.",
            status_code=400,
        )

    band_simulation = payload.band_simulation or BandSimulationParams()
    requested_bands = list(band_simulation.bands)
    grouped = group_radios_by_band(physical_aps)
    warnings: list[str] = []
    executable_bands = []
    for band in requested_bands:
        if grouped.get(band):
            executable_bands.append(band)
        else:
            warnings.append(f"No enabled {band} radios found; skipping {band} RF run.")

    if not executable_bands:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"No enabled radios found for requested RF band(s): {requested_bands}.",
            status_code=400,
        )

    leading_band = executable_bands[0]
    leading_transmitters = grouped[leading_band]
    access_points = physical_aps_to_access_point_list(
        physical_aps,
        band=leading_band,
        fallback_tx_power_dbm=fallback_tx_power_dbm,
    )
    if not access_points:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            f"No access points could be built for RF band {leading_band}.",
            status_code=400,
        )

    first_tx = leading_transmitters[0]
    simulation["frequency_hz"] = first_tx.frequency_ghz * 1_000_000_000.0
    simulation["tx_power_dbm"] = first_tx.tx_power_dbm

    band_metadata = {
        "requested_bands": requested_bands,
        "executed_bands": [leading_band],
        "skipped_bands": [band for band in requested_bands if band != leading_band],
        "leading_band": leading_band,
        "combine_policy": band_simulation.combine_policy,
        "band_aware_status": (
            "leading_band_only" if len(requested_bands) > 1 else "single_band"
        ),
        "bands": build_band_metadata(physical_aps, requested_bands),
        "todo": (
            "Create per-band child jobs and combine results according to "
            f"{band_simulation.combine_policy}."
        ),
    }
    physical_snapshot = [ap.model_dump(mode="json") for ap in physical_aps]
    metadata = {
        **(payload.metadata or {}),
        "physical_aps_snapshot": physical_snapshot,
        "band_metadata": band_metadata,
        "coverage_semantics": COVERAGE_SEMANTICS,
        "normalization_warnings": warnings,
    }
    return {
        "access_points": access_points,
        "simulation": simulation,
        "metadata": metadata,
    }


async def create_rf_run(
    db: Session, payload: RfRunCreate, user: User
) -> RfRunCreatedResponse:
    """RF 시뮬레이션 Job 등록.

    - payload.access_points + payload.simulation 둘 다 있으면 → SageMaker async invoke 흐름
    - 둘 다 없으면 → legacy queue 등록 (deprecated, 외부 worker 가 처리하는 옛 흐름)
    """
    sv = _get_owned_scene_version(db, payload.scene_version_id, user)

    # 새 흐름: backend 선택형 (sagemaker async 또는 local ai_api)
    prepared = _prepare_rf_submit_from_payload(payload)
    if prepared is not None:
        from app.services.rf.rf_job_service import submit_rf_simulation

        rf_run, job = await submit_rf_simulation(
            db,
            scene_version_id=sv.id,
            access_points=prepared["access_points"],
            simulation=prepared["simulation"],
            current_user=user,
            run_type=payload.run_type or "rf_simulate",
            metadata=prepared["metadata"],
            apply_calibration=payload.apply_calibration,
            backend=payload.backend,
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


def delete_rf_run(db: Session, rf_run_id: UUID, user: User) -> None:
    rr = _get_owned_rf_run(db, rf_run_id, user)
    try:
        db.delete(rr)
        db.commit()
    except Exception:
        db.rollback()
        raise


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
        # 프론트는 API 표기(succeeded/pending)로 필터하는데 DB 는 내부값(done/completed/queued)
        # 으로 저장 → 역매핑해서 IN 필터. (응답 normalize 의 역방향)
        _api_to_internal: dict[str, list[str]] = {
            "succeeded": ["done", "completed", "succeeded"],
            "pending": ["queued", "pending"],
            "running": ["running"],
            "failed": ["failed"],
        }
        internal_statuses = _api_to_internal.get(status, [status])
        base = base.where(RfRun.status.in_(internal_statuses))
        count_stmt = count_stmt.where(RfRun.status.in_(internal_statuses))

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
    """storage_url 이 s3:// 면 presigned URL, http(s):// (local backend) 면 그대로 url 채움."""
    resp = RfMapResponse.model_validate(m, from_attributes=True)
    if not m.storage_url:
        return resp
    if m.storage_url.startswith("http://") or m.storage_url.startswith("https://"):
        return resp.model_copy(update={"url": m.storage_url})
    if m.storage_url.startswith("s3://"):
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
