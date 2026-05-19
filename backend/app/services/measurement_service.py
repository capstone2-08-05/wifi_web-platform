from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    MEASUREMENT_DEEP_LINK_SCHEME,
    MEASUREMENT_LINK_TTL_SECONDS,
    MEASUREMENT_WEB_FALLBACK_BASE_URL,
)
from app.models.asset import Asset
from app.models.floor import Floor
from app.models.measurement_link import MeasurementLink
from app.models.measurement_point import MeasurementPoint
from app.models.measurement_session import MeasurementSession
from app.models.scene_version import SceneVersion
from app.schemas.measurement import (
    CoordinateSystemDTO,
    FloorBoundsDTO,
    FloorplanInfoDTO,
    MeasurementLinkContextResponseDTO,
    MeasurementLinkCreateResponseDTO,
    MeasurementPointBatchRequestDTO,
    MeasurementPointBatchResponseDTO,
    MeasurementSessionCompleteRequestDTO,
    MeasurementSessionCompleteResponseDTO,
    MeasurementSessionCreateRequestDTO,
    MeasurementSessionResponseDTO,
    RssiRangeDTO,
)

FLOORPLAN_ASSET_TYPE = "floorplan_image"


def _generate_token() -> str:
    return f"measure_{secrets.token_urlsafe(16)}"


def _append_token(base: str, token: str) -> str:
    parsed = urlparse(base)
    sep = "&" if parsed.query else "?"
    return f"{base}{sep}{urlencode({'token': token})}"


def _validate_uuid(value: str, field: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise AppError(
            ErrorCode.INVALID_UUID_FORMAT,
            f"{field} is not a valid UUID: {value}",
            400,
        ) from exc


def _ensure_link_active(link: MeasurementLink) -> None:
    if link.revoked_at is not None or link.status != "active":
        raise AppError(
            ErrorCode.MEASUREMENT_LINK_EXPIRED,
            f"Measurement link is not active (status={link.status}).",
            410,
        )
    expires_at = link.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AppError(
            ErrorCode.MEASUREMENT_LINK_EXPIRED,
            f"Measurement link expired at {expires_at.isoformat()}",
            410,
        )


def _load_link(db: Session, token: str) -> MeasurementLink:
    link = (
        db.query(MeasurementLink).filter(MeasurementLink.token == token).one_or_none()
    )
    if link is None:
        raise AppError(
            ErrorCode.MEASUREMENT_LINK_NOT_FOUND,
            f"Measurement link not found for token: {token}",
            404,
        )
    return link


def _load_session(db: Session, session_id: str) -> MeasurementSession:
    _validate_uuid(session_id, "session_id")
    session_row = (
        db.query(MeasurementSession)
        .filter(MeasurementSession.id == session_id)
        .one_or_none()
    )
    if session_row is None:
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_NOT_FOUND,
            f"Measurement session not found: {session_id}",
            404,
        )
    return session_row


def _latest_floorplan_asset(db: Session, floor_id: str) -> Asset | None:
    stmt = (
        select(Asset)
        .where(
            Asset.floor_id == floor_id,
            Asset.asset_type == FLOORPLAN_ASSET_TYPE,
        )
        .order_by(Asset.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _resolve_scene_and_asset(
    db: Session, floor_id: str
) -> tuple[str | None, str | None]:
    """Pick the scene_version + asset that this measurement link should anchor to.

    Preference: latest **confirmed** scene_version for the floor (and its
    source_asset_id); fall back to the latest floorplan_image asset on the
    floor when no confirmed scene version exists yet. Draft (is_confirmed=False)
    versions are ignored — measurement links must anchor to a stable, user-
    approved scene so that downstream coordinates stay consistent.
    """
    scene = db.execute(
        select(SceneVersion)
        .where(
            SceneVersion.floor_id == floor_id,
            SceneVersion.is_confirmed.is_(True),
        )
        .order_by(SceneVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()

    if scene is not None:
        asset_id = scene.source_asset_id
        if asset_id is None:
            fallback = _latest_floorplan_asset(db, floor_id)
            asset_id = fallback.id if fallback else None
        return scene.id, asset_id

    fallback = _latest_floorplan_asset(db, floor_id)
    return None, fallback.id if fallback else None


def _floorplan_info_from_asset(db: Session, asset_id: str | None) -> FloorplanInfoDTO:
    if asset_id is None:
        return FloorplanInfoDTO()
    asset = db.get(Asset, asset_id)
    if asset is None:
        return FloorplanInfoDTO()
    metadata = asset.metadata_json or {}
    # S3 객체면 presigned URL 발급 (모바일이 직접 다운로드 가능하게).
    # 비-S3 (옛 로컬 경로) 면 그대로 노출 — 어차피 외부 접근 불가지만 fallback.
    url = asset.storage_url
    if url and url.startswith("s3://"):
        from app.services import _s3
        try:
            url = _s3.presigned_get_url(url)
        except Exception:
            url = None
    return FloorplanInfoDTO(
        url=url,
        width_px=metadata.get("width_px"),
        height_px=metadata.get("height_px"),
        scale_m_per_px=metadata.get("scale_m_per_px"),
    )


def _bounds_from_floorplan(floorplan: FloorplanInfoDTO) -> FloorBoundsDTO:
    if (
        floorplan.width_px is None
        or floorplan.height_px is None
        or floorplan.scale_m_per_px is None
    ):
        return FloorBoundsDTO()
    return FloorBoundsDTO(
        min_x=0.0,
        min_y=0.0,
        max_x=float(floorplan.width_px) * float(floorplan.scale_m_per_px),
        max_y=float(floorplan.height_px) * float(floorplan.scale_m_per_px),
    )


def create_measurement_link(
    db: Session, floor_id: str
) -> MeasurementLinkCreateResponseDTO:
    _validate_uuid(floor_id, "floor_id")

    floor = db.query(Floor).filter(Floor.id == floor_id).one_or_none()
    if floor is None:
        raise AppError(
            ErrorCode.INVALID_FLOOR_ID,
            f"Floor not found: {floor_id}",
            404,
        )

    scene_version_id, asset_id = _resolve_scene_and_asset(db, floor.id)

    token = _generate_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=MEASUREMENT_LINK_TTL_SECONDS)

    link = MeasurementLink(
        token=token,
        project_id=floor.project_id,
        floor_id=floor.id,
        scene_version_id=scene_version_id,
        asset_id=asset_id,
        purpose="rssi_measurement",
        status="active",
        expires_at=expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    deep_link = _append_token(MEASUREMENT_DEEP_LINK_SCHEME, token)
    web_fallback_url = _append_token(MEASUREMENT_WEB_FALLBACK_BASE_URL, token)

    return MeasurementLinkCreateResponseDTO(
        token=token,
        expires_at=link.expires_at,
        deep_link=deep_link,
        web_fallback_url=web_fallback_url,
        qr_payload=deep_link,
    )


def get_measurement_link_context(
    db: Session, token: str
) -> MeasurementLinkContextResponseDTO:
    link = _load_link(db, token)
    _ensure_link_active(link)

    if link.used_at is None:
        link.used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(link)

    floorplan = _floorplan_info_from_asset(db, link.asset_id)
    bounds = _bounds_from_floorplan(floorplan)

    return MeasurementLinkContextResponseDTO(
        token=link.token,
        project_id=link.project_id,
        floor_id=link.floor_id,
        scene_version_id=link.scene_version_id,
        asset_id=link.asset_id,
        expires_at=link.expires_at,
        floorplan=floorplan,
        coordinate_system=CoordinateSystemDTO(),
        bounds=bounds,
        anchor_points=[],
        existing_ap_layouts=[],
    )


def create_measurement_session(
    db: Session, request: MeasurementSessionCreateRequestDTO
) -> MeasurementSessionResponseDTO:
    link = _load_link(db, request.measurement_link_token)
    _ensure_link_active(link)

    session_row = MeasurementSession(
        project_id=link.project_id,
        floor_id=link.floor_id,
        measurement_type=request.measurement_type,
        device_info_json=request.device_info.model_dump(exclude_none=True),
        calibration_json=request.calibration.model_dump(exclude_none=True),
        status="in_progress",
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)

    return MeasurementSessionResponseDTO(
        id=session_row.id,
        project_id=session_row.project_id,
        floor_id=session_row.floor_id,
        scene_version_id=link.scene_version_id,
        asset_id=link.asset_id,
        measurement_type=session_row.measurement_type,
        status=session_row.status,
        created_at=session_row.created_at,
    )


def upload_measurement_points(
    db: Session, session_id: str, request: MeasurementPointBatchRequestDTO
) -> MeasurementPointBatchResponseDTO:
    session_row = _load_session(db, session_id)

    if session_row.status == "completed":
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_ALREADY_COMPLETED,
            f"Session {session_id} is already completed; new points cannot be added.",
            409,
        )

    inserted = 0
    duplicated = 0

    for point in request.points:
        wkt_geom = func.ST_SetSRID(
            func.ST_MakePoint(point.floor_position.x, point.floor_position.y), 0
        )
        row = MeasurementPoint(
            session_id=session_row.id,
            point_geom=wkt_geom,
            z_m=point.floor_position.z,
            rssi_dbm=point.rssi_dbm,
            ap_bssid=point.ap_bssid,
            ap_ssid=point.ap_ssid,
            channel=point.channel,
            frequency_mhz=point.frequency_mhz,
            timestamp_at_point=point.timestamp_at_point,
            ar_tracking_state=point.ar_tracking_state,
            ar_confidence=point.ar_confidence,
            step_index=point.step_index,
            batch_id=request.batch_id,
            client_point_id=point.client_point_id,
            metadata_json=point.metadata_json or {},
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            duplicated += 1
        else:
            inserted += 1

    db.commit()

    return MeasurementPointBatchResponseDTO(
        inserted=inserted,
        duplicated=duplicated,
        session_status=session_row.status,
    )


def complete_measurement_session(
    db: Session, session_id: str, request: MeasurementSessionCompleteRequestDTO
) -> MeasurementSessionCompleteResponseDTO:
    session_row = _load_session(db, session_id)

    if session_row.status == "completed":
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_ALREADY_COMPLETED,
            f"Session {session_id} is already completed.",
            409,
        )

    completed_at = datetime.now(timezone.utc)
    session_row.status = "completed"
    session_row.completed_at = completed_at
    if request.end_position is not None:
        cal = dict(session_row.calibration_json or {})
        cal["end_position"] = request.end_position.model_dump()
        session_row.calibration_json = cal

    stats_row = db.execute(
        select(
            func.count(MeasurementPoint.id),
            func.count(func.distinct(MeasurementPoint.ap_bssid)),
            func.min(MeasurementPoint.rssi_dbm),
            func.max(MeasurementPoint.rssi_dbm),
            func.avg(MeasurementPoint.rssi_dbm),
        ).where(MeasurementPoint.session_id == session_row.id)
    ).one()
    total_points, ap_count, rssi_min, rssi_max, rssi_avg = stats_row

    db.commit()
    db.refresh(session_row)

    created_at = session_row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    duration_seconds = max(int((completed_at - created_at).total_seconds()), 0)

    return MeasurementSessionCompleteResponseDTO(
        id=session_row.id,
        status=session_row.status,
        total_points=int(total_points or 0),
        duration_seconds=duration_seconds,
        ap_count=int(ap_count or 0),
        rssi_range=RssiRangeDTO(
            min=float(rssi_min) if rssi_min is not None else None,
            max=float(rssi_max) if rssi_max is not None else None,
            avg=float(rssi_avg) if rssi_avg is not None else None,
        ),
    )
