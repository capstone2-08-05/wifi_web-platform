from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import AppError, ErrorCode
from app.core.geom import wkb_to_geojson
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
from app.models.object import SceneObject
from app.models.opening import Opening
from app.models.project import Project
from app.models.room import Room
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.models.wall import Wall
from app.schemas.measurement import (
    CoordinateSystemDTO,
    FloorBoundsDTO,
    FloorPositionDTO,
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
    SceneGeometryDTO,
    SceneGeometryObjectDTO,
    SceneGeometryOpeningDTO,
    SceneGeometryRoomDTO,
    SceneGeometryWallDTO,
)

logger = logging.getLogger(__name__)

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


def _session_floor_bounds(
    db: Session, session_row: MeasurementSession
) -> FloorBoundsDTO | None:
    """업로드된 point 의 좌표 범위를 검증하기 위해 세션이 가리키는 floor 의 도면 bounds 를 계산.

    세션 → measurement_link → asset_id 순으로 따라가 asset.metadata_json 의
    width_px/height_px/scale_m_per_px 에서 bounds 를 만든다. 어디라도 결손이면
    None 을 반환해 검증을 스킵 (False positive 방지).
    """
    link = (
        db.query(MeasurementLink)
        .filter(
            MeasurementLink.project_id == session_row.project_id,
            MeasurementLink.floor_id == session_row.floor_id,
        )
        .order_by(MeasurementLink.created_at.desc())
        .first()
    )
    asset_id = link.asset_id if link is not None else None
    if asset_id is None:
        return None
    floorplan = _floorplan_info_from_asset(db, asset_id)
    bounds = _bounds_from_floorplan(floorplan)
    if bounds.max_x <= bounds.min_x or bounds.max_y <= bounds.min_y:
        return None
    return bounds


def _is_inside_bounds(pos: FloorPositionDTO, bounds: FloorBoundsDTO) -> bool:
    return (
        bounds.min_x <= pos.x <= bounds.max_x
        and bounds.min_y <= pos.y <= bounds.max_y
    )


def _spatial_from_floor(
    floor: Floor,
) -> tuple[FloorBoundsDTO | None, CoordinateSystemDTO | None]:
    """floor.spatial_meta 에서 bounds + coordinate_system 추출.

    값이 없으면 (None, None) 을 반환해 호출자가 asset.metadata_json 으로 폴백하게 한다.
    """
    sm = floor.spatial_meta or {}
    bounds_raw = sm.get("bounds_m")
    coord_raw = sm.get("coordinate_system")

    bounds: FloorBoundsDTO | None = None
    if isinstance(bounds_raw, dict):
        try:
            bounds = FloorBoundsDTO(
                min_x=float(bounds_raw.get("min_x", 0.0)),
                min_y=float(bounds_raw.get("min_y", 0.0)),
                max_x=float(bounds_raw.get("max_x", 0.0)),
                max_y=float(bounds_raw.get("max_y", 0.0)),
            )
            if bounds.max_x <= bounds.min_x or bounds.max_y <= bounds.min_y:
                bounds = None
        except (TypeError, ValueError):
            bounds = None

    coord: CoordinateSystemDTO | None = None
    if isinstance(coord_raw, dict):
        try:
            coord = CoordinateSystemDTO(**coord_raw)
        except Exception:
            coord = None

    return bounds, coord


def _scene_geometry_for_version(
    db: Session, scene_version_id: str | None
) -> SceneGeometryDTO:
    """SceneVersion 의 rooms/walls/openings/objects 를 GeoJSON 으로 변환해 응답에 채울 DTO 로."""
    if not scene_version_id:
        return SceneGeometryDTO()

    sv = db.execute(
        select(SceneVersion)
        .options(
            selectinload(SceneVersion.rooms),
            selectinload(SceneVersion.walls),
            selectinload(SceneVersion.openings),
            selectinload(SceneVersion.objects),
        )
        .where(SceneVersion.id == scene_version_id)
    ).scalar_one_or_none()
    if sv is None:
        return SceneGeometryDTO()

    rooms = [
        SceneGeometryRoomDTO(
            id=r.id,
            room_name=r.room_name,
            room_type=r.room_type,
            polygon_geom=wkb_to_geojson(r.polygon_geom),
            centroid_geom=wkb_to_geojson(r.centroid_geom),
        )
        for r in sv.rooms
    ]
    walls = [
        SceneGeometryWallDTO(
            id=w.id,
            wall_role=w.wall_role,
            thickness_m=float(w.thickness_m) if w.thickness_m is not None else None,
            height_m=float(w.height_m) if w.height_m is not None else None,
            centerline_geom=wkb_to_geojson(w.centerline_geom),
            polygon_geom=wkb_to_geojson(w.polygon_geom),
        )
        for w in sv.walls
    ]
    openings = [
        SceneGeometryOpeningDTO(
            id=o.id,
            opening_type=o.opening_type,
            width_m=float(o.width_m) if o.width_m is not None else None,
            height_m=float(o.height_m) if o.height_m is not None else None,
            sill_height_m=(
                float(o.sill_height_m) if o.sill_height_m is not None else None
            ),
            line_geom=wkb_to_geojson(o.line_geom),
        )
        for o in sv.openings
    ]
    objects = [
        SceneGeometryObjectDTO(
            id=obj.id,
            object_type=obj.object_type,
            confidence=float(obj.confidence) if obj.confidence is not None else None,
            z_m=float(obj.z_m) if obj.z_m is not None else None,
            point_geom=wkb_to_geojson(obj.point_geom),
        )
        for obj in sv.objects
    ]
    return SceneGeometryDTO(
        rooms=rooms, walls=walls, openings=openings, objects=objects
    )


def create_measurement_link(
    db: Session,
    floor_id: str,
    *,
    current_user: User,
) -> MeasurementLinkCreateResponseDTO:
    """QR 측정 링크 발급.

    본인 소유 floor 만 허용 — 다른 사용자의 floor 로 임의 토큰을 만들 수 없게 한다.
    floor → project.owner_user_id 체크.
    """
    _validate_uuid(floor_id, "floor_id")

    row = (
        db.query(Floor, Project)
        .join(Project, Floor.project_id == Project.id)
        .filter(Floor.id == floor_id)
        .one_or_none()
    )
    if row is None:
        raise AppError(
            ErrorCode.INVALID_FLOOR_ID,
            f"Floor not found: {floor_id}",
            404,
        )
    floor, project = row
    if project.owner_user_id != current_user.id:
        # 권한 누설 막기 위해 404 와 동일한 메시지로 응답
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

    # 도면 이미지 정보는 항상 asset 에서 (그게 시각화의 source of truth).
    floorplan = _floorplan_info_from_asset(db, link.asset_id)

    # bounds / coordinate_system 은 floor.spatial_meta 우선 → 없으면 asset 폴백.
    # 분리 의도: 도면 asset 이 교체되어도 측정 좌표계는 floor 가 들고 있는다.
    floor = db.get(Floor, link.floor_id)
    bounds: FloorBoundsDTO | None = None
    coord: CoordinateSystemDTO | None = None
    if floor is not None:
        bounds, coord = _spatial_from_floor(floor)
    if bounds is None:
        bounds = _bounds_from_floorplan(floorplan)
    if coord is None:
        coord = CoordinateSystemDTO()

    geometry = _scene_geometry_for_version(db, link.scene_version_id)

    return MeasurementLinkContextResponseDTO(
        token=link.token,
        project_id=link.project_id,
        floor_id=link.floor_id,
        scene_version_id=link.scene_version_id,
        asset_id=link.asset_id,
        expires_at=link.expires_at,
        floorplan=floorplan,
        coordinate_system=coord,
        bounds=bounds,
        geometry=geometry,
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

    # 세션이 가리키는 floor 의 도면 bounds — 점 좌표가 도면 밖이면 metadata 에 마킹.
    # bounds 가 계산 안 되면 (asset metadata 없음) 검증 스킵 (None 처리).
    bounds = _session_floor_bounds(db, session_row)

    inserted = 0
    duplicated = 0
    outliers = 0

    for point in request.points:
        wkt_geom = func.ST_SetSRID(
            func.ST_MakePoint(point.floor_position.x, point.floor_position.y), 0
        )
        metadata = dict(point.metadata_json or {})
        if bounds is not None and not _is_inside_bounds(point.floor_position, bounds):
            metadata["server_outlier"] = True
            outliers += 1
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
            metadata_json=metadata,
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

    if outliers > 0:
        logger.warning(
            "session %s: %d/%d points are outside floor bounds (server_outlier=true marked)",
            session_row.id, outliers, len(request.points),
        )

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
