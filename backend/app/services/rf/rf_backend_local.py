"""Local ai_api backend for RF simulate (alternative to SageMaker async).

SageMaker 경로 대안: 로컬에서 띄운 ai_api 의 `/internal/sionna/run` 을 직접 호출.

핵심 차이:
  - SageMaker: submit 이 비동기로 S3 에 invoke, poll 로 결과 확인
  - Local:     submit 이 백그라운드 thread 에 ai_api 호출을 띄움 (Sionna 자체는
               분 단위 블로킹), 호출 완료 시 thread 가 직접 DB 업데이트.
               poll_rf_job 은 DB status 만 읽으면 됨 (외부 호출 X).

세션 관리: 백그라운드 thread 는 요청 세션을 못 쓰므로 `SessionLocal()` 로 새 세션 생성.

결과 매핑 (SageMaker 결과 구조에 최대한 맞춤 — 프론트가 동일 응답 형태로 받음):
  Job.result_json = {
      "rf_run_id": ..., "backend": "local",
      "heatmap_s3_uri": <imageUrl, http://...>,   # 같은 키 이름 재사용
      "radio_map_s3_uri": None,                   # 로컬은 별도 file 없이 응답에 grid 포함
      "radio_map_meta": {...},
      "local_artifacts": { "imageUrl": ..., "sionna_run_id": ..., "paths": {...} },
  }
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.rf_defaults import (
    DEFAULT_DIFFRACTION,
    DEFAULT_DIFFUSE_REFLECTION,
    DEFAULT_FREQUENCY_HZ,
    DEFAULT_LOS,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MEASUREMENT_PLANE_Z_M,
    DEFAULT_REFRACTION,
    DEFAULT_RESOLUTION_M,
    DEFAULT_SAMPLES_PER_TX,
    DEFAULT_SEED,
    DEFAULT_SPECULAR_REFLECTION,
    DEFAULT_TX_POWER_DBM,
)
from app.db.session import SessionLocal
from app.models import Job, RfRun, SceneVersion, User
from app.models.rf_map import RfMap
from app.services import ai_api_client

logger = logging.getLogger(__name__)

JOB_TYPE_RF_SIMULATE = "rf_simulate"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"

RF_BACKEND_LOCAL = "local"

RF_REQUEST_METADATA_KEYS = (
    "physical_aps_snapshot",
    "band_metadata",
    "coverage_semantics",
    "normalization_warnings",
)


# ============================================================
# Submit
# ============================================================
async def submit_via_local_ai_api(
    db: Session,
    *,
    sv: SceneVersion,
    scene_json: dict[str, Any],
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
    current_user: User,
    run_type: str,
    metadata: dict[str, Any] | None,
    calibration_meta: dict[str, Any],
) -> tuple[RfRun, Job]:
    """RfRun + Job 행 즉시 생성 (status=running) → 백그라운드 thread 가 ai_api 호출.

    submit 자체는 블로킹 없이 즉시 반환. UI 는 기존 SageMaker 폴링 흐름 그대로
    /rf-jobs/{job_id} 를 폴링하면 됨 (poll_rf_job 이 local backend 분기 처리).
    """
    if not access_points:
        raise AppError(
            ErrorCode.INVALID_RF_RUN_STATUS,
            "Local backend requires at least one access point.",
            400,
        )

    payloads = [
        _build_sionna_request_payload(
            scene_json=scene_json,
            floor_id=str(sv.floor_id),
            scene_version_id=str(sv.id),
            ap=ap,
            simulation=simulation,
        )
        for ap in access_points
    ]

    now = _now_utc()
    rf_run = RfRun(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        scene_version_id=sv.id,
        run_type=run_type,
        status=JOB_STATUS_RUNNING,
        request_json={
            "access_points": access_points,
            "simulation": simulation,
            "metadata": metadata or {},
            "calibration": calibration_meta,
            "backend": RF_BACKEND_LOCAL,
            **_request_metadata_fields(metadata),
        },
        metrics_json={},
    )

    input_json: dict[str, Any] = {
        "rf_run_id": None,
        "scene_version_id": str(sv.id),
        "access_points": access_points,
        "simulation": simulation,
        "metadata": metadata or {},
        "requested_by": current_user.email,
        "backend": RF_BACKEND_LOCAL,
        "local": {
            "ai_api_payload_summary": {
                "walls": len(scene_json.get("walls") or []),
                "rooms": len(scene_json.get("rooms") or []),
                "ap_ids": [ap.get("id") for ap in access_points],
            },
        },
    }
    job = Job(
        project_id=sv.project_id,
        floor_id=sv.floor_id,
        job_type=JOB_TYPE_RF_SIMULATE,
        status=JOB_STATUS_RUNNING,
        input_json=input_json,
        result_json={},
        started_at=now,
    )

    try:
        db.add(rf_run)
        db.flush()
        input_json["rf_run_id"] = rf_run.id
        job.input_json = input_json
        db.add(job)
        # rf_run.request_json.access_points 와 동일 좌표로 ApLayout row 자동 생성 —
        # 측정/진단 페이지가 ApLayout 만 보던 기존 코드도 즉시 호환.
        if run_type != "ap_recommendation_verify":
            from app.services.rf.rf_job_service import create_ap_layouts_from_request
            create_ap_layouts_from_request(db, rf_run, access_points)
        db.commit()
        db.refresh(rf_run)
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Failed to persist RF simulation job (local backend): {exc}",
            500,
        ) from exc

    job_id = str(job.id)
    rf_run_id = str(rf_run.id)

    thread = threading.Thread(
        target=_background_run_ai_api,
        kwargs={"job_id": job_id, "rf_run_id": rf_run_id, "payloads": payloads},
        name=f"rf-local-{job_id[:8]}",
        daemon=True,
    )
    thread.start()

    logger.info(
        "RF job submitted (local ai_api) job_id=%s rf_run_id=%s thread=%s",
        job_id, rf_run_id, thread.name,
    )
    return rf_run, job


# ============================================================
# Background worker
# ============================================================
def _background_run_ai_api(
    *, job_id: str, rf_run_id: str, payloads: list[dict[str, Any]]
) -> None:
    """Thread entry point: AP별 ai_api 호출 → element-wise max 합산 → DB 영속화."""
    sim_cfg = (payloads[0].get("simulation") or {}) if payloads else {}
    logger.info(
        "RF job %s: sending %d AP(s) to ai_api — solver=%s propagation=%s mp=%s",
        job_id, len(payloads),
        sim_cfg.get("solver"),
        sim_cfg.get("propagation"),
        payloads[0].get("measurement_plane") if payloads else None,
    )
    try:
        responses: list[dict[str, Any]] = []
        for i, payload in enumerate(payloads):
            ap_id = (payload.get("access_point") or {}).get("id", f"ap{i}")
            logger.info("RF job %s: AP %d/%d id=%s → ai_api", job_id, i + 1, len(payloads), ap_id)
            try:
                response = ai_api_client.run_sionna_simulation(payload=payload)
            except ai_api_client.AiApiClientError as exc:
                logger.warning("RF job %s: AP %d (%s) call failed: %s", job_id, i + 1, ap_id, exc)
                if len(payloads) == 1:
                    raise
                continue
            status = str(response.get("status") or "").lower()
            if status != "succeeded":
                detail = response.get("detail") or response.get("error") or "non-success"
                logger.warning("RF job %s: AP %d status=%s (%s)", job_id, i + 1, status, detail)
                if len(payloads) == 1:
                    _persist_local_failure(
                        job_id=job_id, rf_run_id=rf_run_id,
                        message=f"ai_api status={status}: {detail}",
                    )
                    return
                continue
            responses.append(response)

        if not responses:
            _persist_local_failure(
                job_id=job_id, rf_run_id=rf_run_id,
                message="all AP simulations failed",
            )
            return

        merged = _merge_ap_responses(responses)
        _persist_local_success(job_id=job_id, rf_run_id=rf_run_id, response=merged)

    except ai_api_client.AiApiClientError as exc:
        logger.warning("RF job %s: local ai_api call failed: %s", job_id, exc)
        _persist_local_failure(job_id=job_id, rf_run_id=rf_run_id, message=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.exception("RF job %s: unexpected error during local ai_api call", job_id)
        _persist_local_failure(
            job_id=job_id, rf_run_id=rf_run_id,
            message=f"unexpected error: {exc}",
        )


def _merge_ap_responses(responses: list[dict[str, Any]]) -> dict[str, Any]:
    """여러 AP 시뮬 응답을 하나로 합산. 각 셀에서 RSSI가 가장 강한 AP 값 선택."""
    if len(responses) == 1:
        return responses[0]

    import copy

    base = copy.deepcopy(responses[0])
    base_values: list[list[float]] | None = None
    try:
        base_values = base["artifacts"]["radiomap"]["values_dbm"]
    except (KeyError, TypeError):
        pass

    if base_values is None:
        return base

    for resp in responses[1:]:
        try:
            values: list[list[float]] = resp["artifacts"]["radiomap"]["values_dbm"]
        except (KeyError, TypeError):
            continue
        for r, row in enumerate(values):
            if r >= len(base_values):
                break
            for c, val in enumerate(row):
                if c < len(base_values[r]) and isinstance(val, (int, float)) and val > base_values[r][c]:
                    base_values[r][c] = val

    base["artifacts"]["radiomap"]["values_dbm"] = base_values
    return base


def _persist_local_success(
    *, job_id: str, rf_run_id: str, response: dict[str, Any]
) -> None:
    """ai_api 성공 응답 → Job/RfRun/RfMap 업데이트. 새 DB 세션 사용."""
    db = SessionLocal()
    try:
        job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None:
            logger.warning("RF job %s missing on success persist", job_id)
            return
        if job.status != JOB_STATUS_RUNNING:
            logger.info(
                "RF job %s no longer running (status=%s), skipping persist",
                job_id, job.status,
            )
            return

        artifacts = response.get("artifacts") or {}
        metrics = response.get("metrics") or {}
        sionna_run_id = str(response.get("sionna_run_id") or "")
        image_url = response.get("imageUrl") or artifacts.get("imageUrl")

        radiomap = artifacts.get("radiomap") or {}
        radio_map_meta = {
            "grid_shape": radiomap.get("grid_shape"),
            "bounds_m": radiomap.get("bounds_m"),
            "cell_size_m": (artifacts.get("config") or {}).get("measurement_plane", {}).get("cell_size_m"),
            "rss_dbm": artifacts.get("rssi") or metrics.get("rssi_summary"),
            "coverage_summary": artifacts.get("coverage") or metrics.get("coverage_summary"),
            "valid_cell_count": artifacts.get("valid_cell_count") or metrics.get("valid_cell_count"),
            "valid_ratio": artifacts.get("valid_ratio") or metrics.get("valid_ratio"),
            # heatmap PNG 와 동일한 색 스케일 (vmin/vmax) — 프론트 ColorLegend 에서 사용.
            "color_scale": radiomap.get("color_scale"),
            # Full grid 값 (residual kriging 용 — measurement_estimation 이 prior 로 사용).
            # 100x50 grid 면 ~40KB, 200x200 이면 ~1.3MB. 크긴 한데 sim 당 1회 저장이라 OK.
            # 없거나 너무 크면 estimate_session_coverage 가 pure GP 로 fallback.
            "values_dbm": radiomap.get("values_dbm"),
        }

        rf_run = db.execute(
            select(RfRun).where(RfRun.id == rf_run_id)
        ).scalar_one_or_none()
        if rf_run is not None:
            rf_run.status = JOB_STATUS_DONE
            rf_run.metrics_json = {
                "radio_map": radio_map_meta,
                "runtime": {
                    "mode": "local_ai_api",
                    "sionna_run_id": sionna_run_id,
                },
                "config": artifacts.get("config") or {},
            }
            _create_local_rf_maps(db, rf_run, image_url=image_url, radio_map_meta=radio_map_meta)

        job.status = JOB_STATUS_DONE
        job.result_json = {
            "rf_run_id": rf_run.id if rf_run is not None else None,
            "backend": RF_BACKEND_LOCAL,
            "heatmap_s3_uri": image_url,  # 같은 키 재사용 (http://... 값)
            "radio_map_s3_uri": None,
            "radio_map_meta": radio_map_meta,
            "local_artifacts": {
                "sionna_run_id": sionna_run_id,
                "imageUrl": image_url,
                "paths": {
                    k: artifacts.get(k)
                    for k in (
                        "visualization_path",
                        "valid_mask_path",
                        "geometry_overlay_path",
                        "geometry_debug_path",
                        "runtime_result_path",
                    )
                    if artifacts.get(k)
                },
            },
        }
        job.error_message = None
        job.finished_at = _now_utc()

        db.commit()
        logger.info(
            "RF job %s done (local ai_api) sionna_run_id=%s image_url=%s",
            job_id, sionna_run_id, image_url,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist local ai_api success for job %s: %s", job_id, exc)
    finally:
        db.close()


def _persist_local_failure(
    *, job_id: str, rf_run_id: str, message: str
) -> None:
    """ai_api 실패 → Job/RfRun status=failed. 새 DB 세션 사용."""
    db = SessionLocal()
    try:
        job = db.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        ).scalar_one_or_none()
        if job is None:
            logger.warning("RF job %s missing on failure persist", job_id)
            return
        if job.status != JOB_STATUS_RUNNING:
            return

        job.status = JOB_STATUS_FAILED
        job.error_message = f"[local_ai_api] {message}"
        job.result_json = {
            "backend": RF_BACKEND_LOCAL,
            "error": {
                "backend_code": str(ErrorCode.INTERNAL_SERVER_ERROR),
                "container_code": None,
                "stage": "local_ai_api",
                "message": message,
                "retryable": True,
                "details": {},
            },
        }
        job.finished_at = _now_utc()

        rf_run = db.execute(
            select(RfRun).where(RfRun.id == rf_run_id)
        ).scalar_one_or_none()
        if rf_run is not None:
            rf_run.status = JOB_STATUS_FAILED

        db.commit()
        logger.warning("RF job %s failed (local ai_api): %s", job_id, message)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Failed to persist local ai_api failure for job %s: %s", job_id, exc)
    finally:
        db.close()


def _create_local_rf_maps(
    db: Session, rf_run: RfRun, *, image_url: str | None, radio_map_meta: dict[str, Any]
) -> None:
    """heatmap RfMap row 1개 생성. RF 서버 이미지를 S3에 업로드해 presigned URL로 프론트에 전달."""
    if not image_url:
        return
    cell_size_m = radio_map_meta.get("cell_size_m") or 0.5
    try:
        resolution_cm = max(1, int(round(float(cell_size_m) * 100)))
    except (TypeError, ValueError):
        resolution_cm = 50
    metrics = {
        "rss_dbm": radio_map_meta.get("rss_dbm") or {},
        "coverage_summary": radio_map_meta.get("coverage_summary") or {},
        "valid_cell_count": radio_map_meta.get("valid_cell_count"),
        "valid_ratio": radio_map_meta.get("valid_ratio"),
        "grid_shape": radio_map_meta.get("grid_shape"),
        "color_scale": radio_map_meta.get("color_scale"),
    }

    # RF 서버(localhost:PORT)의 이미지 URL은 브라우저에서 접근 불가 →
    # 백엔드에서 이미지를 다운로드해 S3에 올리고 s3:// URI로 교체.
    # S3 업로드 실패 시 원본 URL 유지 (fallback).
    storage_url = image_url
    try:
        import os as _os
        import uuid as _uuid
        from urllib.parse import urlparse as _urlparse
        import httpx
        from app.services import _s3
        from app.services import ai_api_client as _ai_client

        # image_url 이 "http://localhost:9000/..." 형태면 실제 AI 서버 주소로 교체.
        actual_base = _ai_client._base_url().rstrip("/")
        parsed = _urlparse(image_url)
        download_url = actual_base + parsed.path + (f"?{parsed.query}" if parsed.query else "")

        headers: dict = {}
        _key = _os.getenv("AI_INTERNAL_API_KEY") or _os.getenv("INTERNAL_API_KEY") or ""
        if _key:
            headers["X-Internal-API-Key"] = _key

        resp = httpx.get(download_url, headers=headers, timeout=60)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/png")
        ext = "png" if "png" in content_type else "jpg"
        key = f"rf-maps/{rf_run.id}/{_uuid.uuid4()}.{ext}"
        storage_url = _s3.upload_bytes(key, resp.content, content_type=content_type)
        logger.info("RF 히트맵 S3 업로드 완료: %s → %s", download_url, storage_url)
    except Exception as exc:
        logger.warning("RF 히트맵 S3 업로드 실패, 원본 URL 유지: %s", exc)

    db.add(
        RfMap(
            rf_run_id=rf_run.id,
            map_type="heatmap",
            resolution_cm=resolution_cm,
            storage_url=storage_url,
            bounds_json=radio_map_meta.get("bounds_m") or {},
            metrics_json=metrics,
        )
    )


# ============================================================
# Payload builder: web-platform scene_json → ai_api SionnaRunRequestDto
# ============================================================
def _build_sionna_request_payload(
    *,
    scene_json: dict[str, Any],
    floor_id: str,
    scene_version_id: str,
    ap: dict[str, Any],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    """web-platform AP 1개 + scene/simulation → ai_api `/internal/sionna/run` body.

    멀티 AP 는 submit_via_local_ai_api 가 AP별로 이 함수를 호출하고
    _merge_ap_responses 로 element-wise max 합산한다.
    """
    walls = [
        {
            # scene_json wall 에 id(UUID) 가 있으면 사용, 없으면 순번 fallback.
            # opening.wall_id 가 이 id 를 참조하므로 반드시 일치해야 함.
            "id": str(w.get("id") or f"w{i}"),
            "start_xy": [float(w["x1"]), float(w["y1"])],
            "end_xy": [float(w["x2"]), float(w["y2"])],
            "height_m": float(w.get("height") or 2.6),
            "thickness_m": float(w.get("thickness") or 0.12),
            "material_id": str(w.get("material") or "plasterboard"),
            "sionna_material_key": str(w.get("material") or "plasterboard"),
        }
        for i, w in enumerate(scene_json.get("walls") or [])
    ]
    rooms = [
        {
            "id": f"r{i}",
            "polygon_xy": [[float(p[0]), float(p[1])] for p in (r.get("points") or [])],
        }
        for i, r in enumerate(scene_json.get("rooms") or [])
    ]
    openings = [
        {
            "id": str(op.get("id") or f"op{j}"),
            "wall_id": str(op["wall_id"]),
            # OpeningObject.kind 은 필수 — scene_json 에 있으면 사용, 없으면 "door" fallback
            "kind": str(op.get("kind") or op.get("opening_type") or "door"),
            "center_xy": [float(op["center_xy"][0]), float(op["center_xy"][1])],
            "width_m": float(op["width_m"]),
            "height_m": float(op["height_m"]),
            "bottom_z_m": float(op.get("bottom_z_m") or 0.0),
            "sionna_material_key": str(op.get("sionna_material_key") or "wood"),
            "material_id": str(op.get("material_id") or op.get("sionna_material_key") or "wood"),
        }
        for j, op in enumerate(scene_json.get("openings") or [])
        if op.get("wall_id")
    ]

    ap_id = str(ap.get("id") or "ap0")
    ap_position = [
        float(ap.get("x_m") if ap.get("x_m") is not None else ap.get("x") if ap.get("x") is not None else 0.0),
        float(ap.get("y_m") if ap.get("y_m") is not None else ap.get("y") if ap.get("y") is not None else 0.0),
        float(ap.get("z_m") if ap.get("z_m") is not None else ap.get("z") if ap.get("z") is not None else 1.2),
    ]

    # 모든 fallback 은 `app/core/rf_defaults.py` 에서 import — 같은 source of truth 유지.
    # 정상 flow 에선 `RfSimulationParams.model_dump()` 가 디폴트 채워서 들어오므로
    # .get(key, FALLBACK) 의 fallback 은 dead-code 지만, 직접 호출 시 안전망.
    frequency_hz = float(simulation.get("frequency_hz") or DEFAULT_FREQUENCY_HZ)
    frequency_ghz = frequency_hz / 1e9
    tx_power_dbm = float(simulation.get("tx_power_dbm") or DEFAULT_TX_POWER_DBM)

    return {
        "engine": "sionna_rt",
        "floor_id": floor_id,
        "scene": {
            "scene_id": scene_version_id,
            "walls": walls,
            "rooms": rooms,
            "openings": openings,
            "furniture": [],
        },
        "access_point": {
            "id": ap_id,
            "position_m": ap_position,
            "tx_power_dbm": tx_power_dbm,
            "frequency_ghz": frequency_ghz,
        },
        "measurement_plane": {
            "z_m": float(simulation.get("measurement_plane_z_m") or DEFAULT_MEASUREMENT_PLANE_Z_M),
            "cell_size_m": float(simulation.get("resolution_m") or DEFAULT_RESOLUTION_M),
        },
        "simulation": {
            "physical": {
                "frequency_ghz": frequency_ghz,
                "tx_power_dbm": tx_power_dbm,
            },
            "solver": {
                "max_depth": int(simulation.get("max_depth") or DEFAULT_MAX_DEPTH),
                "samples_per_tx": int(simulation.get("samples_per_tx") or DEFAULT_SAMPLES_PER_TX),
                "seed": int(simulation.get("seed") or DEFAULT_SEED),
            },
            # Propagation — 항상 명시 전송. ai_api 디폴트로 fallback 안 함.
            "propagation": {
                "los": bool(simulation.get("los", DEFAULT_LOS)),
                "specular_reflection": bool(
                    simulation.get("specular_reflection", DEFAULT_SPECULAR_REFLECTION)
                ),
                "refraction": bool(simulation.get("refraction", DEFAULT_REFRACTION)),
                "diffuse_reflection": bool(
                    simulation.get("diffuse_reflection", DEFAULT_DIFFUSE_REFLECTION)
                ),
                "diffraction": bool(simulation.get("diffraction", DEFAULT_DIFFRACTION)),
            },
        },
    }


# ============================================================
# Helpers
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _request_metadata_fields(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {key: metadata[key] for key in RF_REQUEST_METADATA_KEYS if key in metadata}
