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
from app.core.geom import wkb_to_geojson
from app.models.asset import Asset
from app.models.floor import Floor
from app.models.measurement_link import MeasurementLink
from app.models.measurement_point import MeasurementPoint
from app.models.measurement_session import MeasurementSession
from app.models.project import Project
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.measurement import (
    CoordinateSystemDTO,
    DetectedApResponseDTO,
    FloorBoundsDTO,
    FloorPositionDTO,
    FloorplanInfoDTO,
    MeasurementLinkContextResponseDTO,
    MeasurementLinkCreateResponseDTO,
    MeasurementPointBatchRequestDTO,
    MeasurementPointBatchResponseDTO,
    MeasurementPointResponseDTO,
    MeasurementSessionCompleteRequestDTO,
    MeasurementSessionCompleteResponseDTO,
    MeasurementSessionCreateRequestDTO,
    MeasurementSessionResponseDTO,
    RssiRangeDTO,
)
from app.schemas.pagination import PaginatedResponse

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


# ============================================================
# §10.4 / §10.5 조회 API (JWT — 본인 소유 floor 의 데이터만)
# ============================================================
def _load_owned_session(
    db: Session, session_id: str, user: User
) -> MeasurementSession:
    _validate_uuid(session_id, "session_id")
    row = (
        db.query(MeasurementSession)
        .join(Project, MeasurementSession.project_id == Project.id)
        .filter(
            MeasurementSession.id == session_id,
            Project.owner_user_id == user.id,
        )
        .one_or_none()
    )
    if row is None:
        raise AppError(
            ErrorCode.MEASUREMENT_SESSION_NOT_FOUND,
            f"Measurement session not found: {session_id}",
            404,
        )
    return row


def _validate_owned_floor(db: Session, floor_id: str, user: User) -> None:
    _validate_uuid(floor_id, "floor_id")
    floor = (
        db.query(Floor)
        .join(Project, Floor.project_id == Project.id)
        .filter(Floor.id == floor_id, Project.owner_user_id == user.id)
        .one_or_none()
    )
    if floor is None:
        raise AppError(
            ErrorCode.FLOOR_NOT_FOUND,
            f"Floor not found: {floor_id}",
            404,
        )


def _session_to_response(row: MeasurementSession) -> MeasurementSessionResponseDTO:
    # MeasurementSession 자체엔 asset_id/scene_version_id 가 없음 (link 가 가짐).
    # 호환을 위해 None 으로 둠 — 필요시 link 통해 조회 가능.
    return MeasurementSessionResponseDTO(
        id=row.id,
        project_id=row.project_id,
        floor_id=row.floor_id,
        scene_version_id=None,
        asset_id=None,
        measurement_type=row.measurement_type,
        status=row.status,
        created_at=row.created_at,
    )


def get_session(
    db: Session, session_id: str, user: User
) -> MeasurementSessionResponseDTO:
    """§10.4 — 측정 세션 단건 조회."""
    return _session_to_response(_load_owned_session(db, session_id, user))


def _point_to_response(row: MeasurementPoint) -> MeasurementPointResponseDTO:
    gj = wkb_to_geojson(row.point_geom)
    coords = (gj or {}).get("coordinates") or [0.0, 0.0]
    z = float(row.z_m) if row.z_m is not None else 0.0
    return MeasurementPointResponseDTO(
        id=row.id,
        session_id=row.session_id,
        client_point_id=row.client_point_id,
        batch_id=row.batch_id,
        floor_position=FloorPositionDTO(
            x=float(coords[0]), y=float(coords[1]), z=z
        ),
        rssi_dbm=float(row.rssi_dbm) if row.rssi_dbm is not None else None,
        ap_bssid=row.ap_bssid,
        ap_ssid=row.ap_ssid,
        channel=row.channel,
        frequency_mhz=row.frequency_mhz,
        timestamp_at_point=row.timestamp_at_point,
        ar_tracking_state=row.ar_tracking_state,
        ar_confidence=float(row.ar_confidence) if row.ar_confidence is not None else None,
        step_index=row.step_index,
        metadata_json=row.metadata_json or {},
        created_at=row.created_at,
    )


def list_points(
    db: Session,
    session_id: str,
    user: User,
    page: int,
    page_size: int,
) -> PaginatedResponse[MeasurementPointResponseDTO]:
    """§10.4 — 세션 내 측정 포인트 페이지네이션 조회."""
    _load_owned_session(db, session_id, user)

    total = db.execute(
        select(func.count(MeasurementPoint.id)).where(
            MeasurementPoint.session_id == session_id
        )
    ).scalar() or 0

    rows = (
        db.execute(
            select(MeasurementPoint)
            .where(MeasurementPoint.session_id == session_id)
            .order_by(MeasurementPoint.step_index.asc().nullslast(), MeasurementPoint.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PaginatedResponse[MeasurementPointResponseDTO](
        items=[_point_to_response(r) for r in rows],
        page=page,
        page_size=page_size,
        total=int(total),
    )


def list_sessions_by_floor(
    db: Session,
    floor_id: str,
    user: User,
    page: int,
    page_size: int,
    status: str | None = None,
) -> PaginatedResponse[MeasurementSessionResponseDTO]:
    """§10.4 — 층의 모든 측정 세션 목록 (페이지네이션 + status 필터)."""
    _validate_owned_floor(db, floor_id, user)

    base = (
        db.query(MeasurementSession)
        .filter(MeasurementSession.floor_id == floor_id)
    )
    if status is not None:
        base = base.filter(MeasurementSession.status == status)

    total = base.count()
    rows = (
        base.order_by(MeasurementSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse[MeasurementSessionResponseDTO](
        items=[_session_to_response(r) for r in rows],
        page=page,
        page_size=page_size,
        total=int(total),
    )


def estimate_session_coverage(
    db: Session,
    session_id: str,
    user: User,
    grid_resolution_m: float = 0.5,
) -> "EstimatedCoverageResponseDTO":
    """§81 — 세션의 측정점들을 GP regression 으로 dense map 추정.

    1. 권한 + 세션 로드
    2. 측정점 (x, y, rssi) 로드 — rssi NULL 인 점은 제외
    3. floor 의 도면 bounds 계산 (없으면 측정점 bounding box)
    4. GP fit + predict
    5. heatmap PNG 생성 + S3 업로드
    6. presigned URL 응답
    """
    # lazy import — 무거운 sklearn / matplotlib 을 모듈 import 단에서 끌어오지 않음
    from app.schemas.measurement import (
        EstimatedCoverageResponseDTO,
        EstimatedRssiRangeDTO,
    )
    from app.services._s3 import presigned_get_url
    from app.services.measurement_estimation.gp_estimator import estimate_coverage
    from app.services.measurement_estimation.heatmap import render_and_upload

    session_row = _load_owned_session(db, session_id, user)

    # 측정점 (rssi 있는 것만) 로드
    rows = (
        db.execute(
            select(MeasurementPoint).where(
                MeasurementPoint.session_id == session_row.id,
                MeasurementPoint.rssi_dbm.isnot(None),
            )
        )
        .scalars()
        .all()
    )

    points: list[tuple[float, float, float]] = []
    for r in rows:
        gj = wkb_to_geojson(r.point_geom)
        coords = (gj or {}).get("coordinates") or [0.0, 0.0]
        points.append((float(coords[0]), float(coords[1]), float(r.rssi_dbm)))

    if len(points) < 3:
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            f"Need at least 3 measurement points with RSSI for estimation (got {len(points)})",
            400,
        )

    # bounds — floor 의 floorplan 메타데이터 → 없으면 측정점 bbox
    asset = _latest_floorplan_asset(db, str(session_row.floor_id))
    floorplan = _floorplan_info_from_asset(db, asset.id if asset else None)
    bounds_dto = _bounds_from_floorplan(floorplan)
    if bounds_dto.max_x <= 0 or bounds_dto.max_y <= 0:
        # fallback: 측정점 bbox + 1m 마진
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        bounds_dto = FloorBoundsDTO(
            min_x=min(xs) - 1.0,
            min_y=min(ys) - 1.0,
            max_x=max(xs) + 1.0,
            max_y=max(ys) + 1.0,
        )
    bounds_tuple = (bounds_dto.min_x, bounds_dto.min_y, bounds_dto.max_x, bounds_dto.max_y)

    # GP 학습 + 예측
    estimate = estimate_coverage(
        points, bounds=bounds_tuple, grid_resolution_m=grid_resolution_m
    )

    # heatmap 생성 + S3
    mean_uri, std_uri = render_and_upload(estimate, str(session_row.id), points)

    return EstimatedCoverageResponseDTO(
        heatmap_url=presigned_get_url(mean_uri),
        uncertainty_url=presigned_get_url(std_uri),
        bounds=bounds_dto,
        grid_shape=list(estimate.mean_grid.shape),
        grid_resolution_m=grid_resolution_m,
        rssi_range=EstimatedRssiRangeDTO(
            min=float(estimate.mean_grid.min()),
            max=float(estimate.mean_grid.max()),
            mean=float(estimate.mean_grid.mean()),
        ),
        uncertainty_max_db=float(estimate.std_grid.max()),
        input_point_count=estimate.input_point_count,
        kernel_repr=estimate.kernel_repr,
    )


def list_detected_aps(
    db: Session, session_id: str, user: User
) -> list[DetectedApResponseDTO]:
    """§10.5 — 세션 내 ap_bssid 별 집계."""
    _load_owned_session(db, session_id, user)

    rows = db.execute(
        select(
            MeasurementPoint.ap_bssid,
            func.max(MeasurementPoint.ap_ssid).label("ap_ssid"),
            func.max(MeasurementPoint.channel).label("channel"),
            func.max(MeasurementPoint.frequency_mhz).label("frequency_mhz"),
            func.count(MeasurementPoint.id).label("point_count"),
            func.avg(MeasurementPoint.rssi_dbm).label("rssi_avg"),
            func.min(MeasurementPoint.rssi_dbm).label("rssi_min"),
            func.max(MeasurementPoint.rssi_dbm).label("rssi_max"),
        )
        .where(
            MeasurementPoint.session_id == session_id,
            MeasurementPoint.ap_bssid.isnot(None),
        )
        .group_by(MeasurementPoint.ap_bssid)
        .order_by(func.count(MeasurementPoint.id).desc())
    ).all()

    return [
        DetectedApResponseDTO(
            ap_bssid=r.ap_bssid,
            ap_ssid=r.ap_ssid,
            channel=r.channel,
            frequency_mhz=r.frequency_mhz,
            point_count=int(r.point_count),
            rssi_avg=float(r.rssi_avg) if r.rssi_avg is not None else None,
            rssi_min=float(r.rssi_min) if r.rssi_min is not None else None,
            rssi_max=float(r.rssi_max) if r.rssi_max is not None else None,
        )
        for r in rows
    ]
