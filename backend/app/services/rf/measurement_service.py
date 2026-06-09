from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from app.models.ap_layout import ApLayout
from app.models.floor import Floor
from app.models.measurement_link import MeasurementLink
from app.models.measurement_point import MeasurementPoint
from app.models.measurement_session import MeasurementSession
from app.models.project import Project
from app.models.rf_run import RfRun
from app.models.scene_version import SceneVersion
from app.models.user import User
from app.schemas.rf.measurement import (
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


def _compact_dict(values: dict[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def _build_channel_observation(point) -> dict[str, object]:
    connected_ap = _compact_dict(
        {
            "bssid": point.ap_bssid,
            "ssid": point.ap_ssid,
            "channel": point.channel,
            "frequency_mhz": point.frequency_mhz,
            "channel_width_mhz": point.channel_width_mhz,
            "center_frequency_mhz": point.center_frequency_mhz,
            "link_speed_mbps": point.link_speed_mbps,
            "tx_link_speed_mbps": point.tx_link_speed_mbps,
            "rx_link_speed_mbps": point.rx_link_speed_mbps,
            "noise_dbm": point.noise_dbm,
            "wifi_standard": point.wifi_standard,
        }
    )
    scan_results = [
        scan.model_dump(mode="json", exclude_none=True)
        for scan in point.wifi_scan_results
    ]
    same_channel_count = 0
    adjacent_channel_count = 0
    if point.channel is not None:
        for scan in point.wifi_scan_results:
            if scan.channel is None:
                continue
            if scan.channel == point.channel:
                same_channel_count += 1
            elif abs(scan.channel - point.channel) <= 4:
                adjacent_channel_count += 1

    return _compact_dict(
        {
            "connected_ap": connected_ap or None,
            "scan_results": scan_results or None,
            "scan_result_count": len(scan_results) if scan_results else None,
            "same_channel_count": same_channel_count if scan_results else None,
            "adjacent_channel_count": adjacent_channel_count if scan_results else None,
        }
    )


def _measurement_point_metadata(point) -> dict[str, object]:
    metadata = dict(point.metadata_json or {})
    channel_observation = _build_channel_observation(point)
    if channel_observation:
        existing = metadata.get("channel_observation")
        if isinstance(existing, dict):
            channel_observation = {**existing, **channel_observation}
        metadata["channel_observation"] = channel_observation
    return metadata


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
    db: Session, floor_id: str, scene_version_id: str | None = None
) -> tuple[str | None, str | None]:
    """Pick the scene_version + asset that this measurement link should anchor to.

    When a scene_version_id is provided, the measurement link is anchored to
    exactly that version. Otherwise, use the latest confirmed scene for the
    floor. Do not pair a scene with the floor's latest unrelated asset.
    """
    if scene_version_id:
        _validate_uuid(scene_version_id, "scene_version_id")
        scene = db.execute(
            select(SceneVersion).where(
                SceneVersion.id == scene_version_id,
                SceneVersion.floor_id == floor_id,
            )
        ).scalar_one_or_none()
        if scene is None:
            raise AppError(
                ErrorCode.SCENE_VERSION_NOT_FOUND,
                f"Scene version {scene_version_id} not found for floor {floor_id}.",
                404,
            )
    else:
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
        return scene.id, scene.source_asset_id

    fallback = _latest_floorplan_asset(db, floor_id)
    return None, fallback.id if fallback else None


def _floorplan_info_from_asset(
    db: Session,
    asset_id: str | None,
    *,
    link_token: str | None = None,
    base_url: str | None = None,
) -> FloorplanInfoDTO:
    """asset → mobile 이 다운로드 가능한 URL 로 변환.

    - `s3://`: presigned GET URL (모바일이 직접 다운로드)
    - `file://`: backend 의 token-인증 public 라우트 URL 로 변환 (link_token 필수).
      모바일은 PC 의 로컬 파일을 못 봐서, JWT 우회 + token 검증되는 streaming
      endpoint 가 필요. link_token 없으면 None (예: 권한 없는 호출).
    - 기타 스킴 / null: URL 없음 → 모바일 UI 가 "도면 자산 없음" 표시
    """
    if asset_id is None:
        return FloorplanInfoDTO()
    asset = db.get(Asset, asset_id)
    if asset is None:
        return FloorplanInfoDTO()
    metadata = asset.metadata_json or {}
    url = asset.storage_url
    if url and url.startswith("s3://"):
        from app.services import _s3
        try:
            url = _s3.presigned_get_url(url)
        except Exception:
            url = None
    elif url and url.startswith("file://"):
        # 로컬 dev mode — backend 가 자체 스트리밍 endpoint 로 노출.
        # base_url 이 있으면 absolute URL, 없으면 relative (모바일은 absolute 필요).
        if link_token:
            path = f"/measurement-links/{link_token}/floorplan-image"
            url = f"{base_url.rstrip('/')}{path}" if base_url else path
        else:
            url = None
    else:
        # 알 수 없는 스킴 — 모바일이 못 씀.
        url = None
    return FloorplanInfoDTO(
        url=url,
        width_px=metadata.get("width_px"),
        height_px=metadata.get("height_px"),
        scale_m_per_px=metadata.get("scale_m_per_px"),
    )


def _bounds_from_scene_walls(
    db: Session, scene_version_id: str | None
) -> FloorBoundsDTO | None:
    """Scene version 의 벽/개구부 좌표로 bbox 계산.

    프론트 MeasurementCanvas 의 viewBox 도 같은 (walls + openings) 기준으로 잡힘.
    히트맵 PNG 가 도면 위에 정확히 깔리려면 같은 좌표계 bounds 가 필요.
    scene 이 없거나 벽/개구부 좌표가 없으면 None — 호출측에서 다음 fallback 사용.
    """
    from app.core.geom import wkb_to_geojson
    from app.models.opening import Opening
    from app.models.wall import Wall

    if not scene_version_id:
        return None
    scene = db.get(SceneVersion, scene_version_id)
    if scene is None:
        return None

    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for w in db.execute(
        select(Wall).where(Wall.scene_version_id == scene_version_id)
    ).scalars().all():
        gj = wkb_to_geojson(w.centerline_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        for x, y in gj["coordinates"]:
            if x < minx: minx = x
            if y < miny: miny = y
            if x > maxx: maxx = x
            if y > maxy: maxy = y
    for o in db.execute(
        select(Opening).where(Opening.scene_version_id == scene_version_id)
    ).scalars().all():
        gj = wkb_to_geojson(o.line_geom)
        if not gj or gj.get("type") != "LineString":
            continue
        for x, y in gj["coordinates"]:
            if x < minx: minx = x
            if y < miny: miny = y
            if x > maxx: maxx = x
            if y > maxy: maxy = y
    if minx == float("inf"):
        return None
    return FloorBoundsDTO(min_x=minx, min_y=miny, max_x=maxx, max_y=maxy)


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


def _valid_bounds(bounds: FloorBoundsDTO | None) -> bool:
    return bool(bounds and bounds.max_x > bounds.min_x and bounds.max_y > bounds.min_y)


def _latest_rf_run_for_scene(
    db: Session, floor_id: str, scene_version_id: str | None
) -> RfRun | None:
    filters = [
        RfRun.floor_id == floor_id,
        RfRun.status.in_(["done", "completed", "succeeded"]),
        RfRun.run_type != "ap_recommendation_verify",
    ]
    if scene_version_id:
        filters.append(RfRun.scene_version_id == scene_version_id)
    return db.execute(
        select(RfRun).where(*filters).order_by(RfRun.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _point_xy(point_geom: object) -> tuple[float, float] | None:
    gj = wkb_to_geojson(point_geom)
    coords = (gj or {}).get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    try:
        return float(coords[0]), float(coords[1])
    except (TypeError, ValueError):
        return None


def _existing_ap_layouts_for_context(
    db: Session, floor_id: str, scene_version_id: str | None
) -> list[dict[str, object]]:
    """Return AP positions with the measurement context so mobile can draw them.

    Prefer saved ap_layouts for the latest RF run. If no layout rows exist, fall
    back to the access_points embedded in the run request, which is how older
    simulation runs exposed AP positions.
    """
    layout_filters = [
        RfRun.floor_id == floor_id,
        RfRun.run_type != "ap_recommendation_verify",
    ]
    if scene_version_id:
        layout_filters.append(RfRun.scene_version_id == scene_version_id)
    rf_runs = db.execute(
        select(RfRun)
        .where(*layout_filters)
        .order_by(RfRun.created_at.desc())
    ).scalars().all()

    for candidate_run in rf_runs:
        rows = db.execute(
            select(ApLayout)
            .where(ApLayout.rf_run_id == candidate_run.id)
            .order_by(ApLayout.created_at.asc())
        ).scalars().all()
        layouts: list[dict[str, object]] = []
        for row in rows:
            xy = _point_xy(row.point_geom)
            if xy is None:
                continue
            x, y = xy
            layouts.append(
                {
                    "id": row.id,
                    "rf_run_id": row.rf_run_id,
                    "ap_name": row.ap_name,
                    "x_m": x,
                    "y_m": y,
                    "z_m": float(row.z_m) if row.z_m is not None else None,
                    "power_dbm": float(row.power_dbm) if row.power_dbm is not None else None,
                    "channel_info_json": row.channel_info_json or {},
                    "point_geom": {"type": "Point", "coordinates": [x, y]},
                }
            )
        if layouts:
            return layouts

    rf_run = rf_runs[0] if rf_runs else _latest_rf_run_for_scene(db, floor_id, scene_version_id)
    if rf_run is None:
        return []

    raw = (rf_run.request_json or {}).get("access_points")
    if not isinstance(raw, list):
        return []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        try:
            x = float(entry.get("x_m", entry.get("x")))
            y = float(entry.get("y_m", entry.get("y")))
        except (TypeError, ValueError):
            continue
        ap_id = entry.get("id")
        label = str(ap_id) if ap_id else f"AP-{index + 1}"
        layouts.append(
            {
                "id": label,
                "rf_run_id": rf_run.id,
                "ap_name": label,
                "x_m": x,
                "y_m": y,
                "z_m": entry.get("z_m"),
                "power_dbm": entry.get("power_dbm"),
                "channel_info_json": entry.get("channel_info_json") or {},
                "point_geom": {"type": "Point", "coordinates": [x, y]},
            }
        )
    return layouts


def create_measurement_link(
    db: Session,
    floor_id: str,
    *,
    recommended_measurement_purpose: str = "calibration",
    scene_version_id: str | None = None,
) -> MeasurementLinkCreateResponseDTO:
    _validate_uuid(floor_id, "floor_id")
    purpose = (
        recommended_measurement_purpose
        if recommended_measurement_purpose in {"calibration", "reference", "validation", "unknown"}
        else "calibration"
    )

    floor = db.query(Floor).filter(Floor.id == floor_id).one_or_none()
    if floor is None:
        raise AppError(
            ErrorCode.INVALID_FLOOR_ID,
            f"Floor not found: {floor_id}",
            404,
        )

    resolved_scene_version_id, asset_id = _resolve_scene_and_asset(
        db, floor.id, scene_version_id
    )

    token = _generate_token()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=MEASUREMENT_LINK_TTL_SECONDS)

    link = MeasurementLink(
        token=token,
        project_id=floor.project_id,
        floor_id=floor.id,
        scene_version_id=resolved_scene_version_id,
        asset_id=asset_id,
        purpose=purpose,
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


def resolve_floorplan_image_for_link(
    db: Session, token: str
) -> tuple[Path, str]:
    """측정 link token 으로 인증되는 floorplan 이미지 path + mime 반환.

    `/measurement-links/{token}/floorplan-image` 라우트가 사용. JWT 우회 — link token
    자체가 권한 증명 (이미 컨텍스트/세션 생성에 쓰는 동일 토큰이라 동등 권한).

    - link revoked / expired → 410 AppError (`_ensure_link_active`)
    - asset 없거나 file:// 아님 → 404
    """
    link = _load_link(db, token)
    _ensure_link_active(link)
    if link.asset_id is None:
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "This measurement link has no floorplan asset.",
            status_code=404,
        )
    asset = db.get(Asset, link.asset_id)
    if asset is None:
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Asset {link.asset_id} not found.",
            status_code=404,
        )
    url_value = asset.storage_url or ""
    if not url_value.startswith("file://"):
        # S3 자산이면 모바일이 _floorplan_info_from_asset 의 presigned URL 을 직접 받음 —
        # 이 라우트로 오면 안 되는 경로. 안내성 404.
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset is not a local file (use presigned URL from /context instead).",
            status_code=404,
        )
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url_value)
    raw_path = unquote(parsed.path)
    # 윈도우: file:///C:/foo → /C:/foo 형태로 path 가 들어옴, 앞 / 떼야 OS path 됨.
    if raw_path.startswith("/") and len(raw_path) > 3 and raw_path[2] == ":":
        raw_path = raw_path[1:]
    path = Path(raw_path)
    if not path.is_file():
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Local floorplan file missing: {path}",
            status_code=404,
        )
    return path, (asset.mime_type or "image/png")


def get_measurement_link_context(
    db: Session, token: str, *, base_url: str | None = None,
) -> MeasurementLinkContextResponseDTO:
    link = _load_link(db, token)
    _ensure_link_active(link)

    if link.used_at is None:
        link.used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(link)

    # link_token + base_url 을 넘겨 file:// asset 도 모바일이 접근 가능한 URL 생성.
    floorplan = _floorplan_info_from_asset(
        db, link.asset_id, link_token=token, base_url=base_url,
    )
    floorplan_bounds = _bounds_from_floorplan(floorplan)
    scene_bounds = _bounds_from_scene_walls(db, link.scene_version_id)
    bounds = floorplan_bounds if _valid_bounds(floorplan_bounds) else (scene_bounds or floorplan_bounds)

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
        existing_ap_layouts=_existing_ap_layouts_for_context(
            db, link.floor_id, link.scene_version_id
        ),
        recommended_measurement_purpose=link.purpose
        if link.purpose in {"calibration", "reference", "validation", "unknown"}
        else "calibration",
    )


def create_measurement_session(
    db: Session, request: MeasurementSessionCreateRequestDTO
) -> MeasurementSessionResponseDTO:
    link = _load_link(db, request.measurement_link_token)
    _ensure_link_active(link)

    session_row = MeasurementSession(
        project_id=link.project_id,
        floor_id=link.floor_id,
        scene_version_id=link.scene_version_id,
        asset_id=link.asset_id,
        measurement_type=request.measurement_type,
        measurement_purpose=request.measurement_purpose,
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
        measurement_purpose=session_row.measurement_purpose,
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
            sinr_db=point.sinr_db,
            latency_ms=point.latency_ms,
            throughput_mbps=point.throughput_mbps,
            measurement_purpose=point.measurement_purpose,
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
            metadata_json=_measurement_point_metadata(point),
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
        scene_version_id=row.scene_version_id,
        asset_id=row.asset_id,
        measurement_type=row.measurement_type,
        measurement_purpose=row.measurement_purpose,
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
        sinr_db=float(row.sinr_db) if row.sinr_db is not None else None,
        latency_ms=float(row.latency_ms) if row.latency_ms is not None else None,
        throughput_mbps=float(row.throughput_mbps) if row.throughput_mbps is not None else None,
        measurement_purpose=row.measurement_purpose,
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
    ap_bssid: str | None = None,
) -> PaginatedResponse[MeasurementPointResponseDTO]:
    """§10.4 — 세션 내 측정 포인트 페이지네이션 조회."""
    _load_owned_session(db, session_id, user)

    filters = [MeasurementPoint.session_id == session_id]
    if ap_bssid:
        filters.append(func.lower(MeasurementPoint.ap_bssid) == ap_bssid.lower())

    total = db.execute(
        select(func.count(MeasurementPoint.id)).where(*filters)
    ).scalar() or 0

    rows = (
        db.execute(
            select(MeasurementPoint)
            .where(*filters)
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


def _try_load_sim_grid_for_scene(
    db: Session, floor_id: str, scene_version_id: str | None,
) -> tuple["np.ndarray", "np.ndarray", "np.ndarray"] | None:
    """scene_version 기준 최근 succeeded RfRun 의 radio_map values_dbm + xs/ys 추출.

    Returns:
        (grid, xs, ys) — residual kriging 의 prior 로 사용.
        None — sim 없거나 values_dbm 누락 or 형식 오류.
    """
    import numpy as np
    from app.models.rf_run import RfRun

    # scene_version_id 가 있는 세션은 반드시 같은 도면의 sim prior 만 사용.
    filters = [
        RfRun.floor_id == floor_id,
        RfRun.status.in_(["done", "completed", "succeeded"]),
    ]
    if scene_version_id:
        filters.append(RfRun.scene_version_id == scene_version_id)
    rf_run = db.execute(
        select(RfRun)
        .where(*filters)
        .order_by(RfRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rf_run is None:
        return None

    radio_map = (rf_run.metrics_json or {}).get("radio_map") or {}
    values = radio_map.get("values_dbm")
    bounds = radio_map.get("bounds_m") or {}
    if not isinstance(values, list) or not values:
        return None
    try:
        grid = np.asarray(values, dtype=np.float64)
    except Exception:
        return None
    if grid.ndim != 2 or grid.size == 0:
        return None

    # bounds_m → xs/ys 배열. 미지정 시 grid_shape 만 있으면 0 origin 으로 fallback.
    H, W = grid.shape
    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", float(W)))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", float(H)))
    if max_x <= min_x or max_y <= min_y:
        return None
    xs = np.linspace(min_x, max_x, W)
    ys = np.linspace(min_y, max_y, H)
    return grid, xs, ys


def estimate_session_coverage(
    db: Session,
    session_id: str,
    user: User,
    grid_resolution_m: float = 0.5,
    method: str = "auto",
    ap_bssid: str | None = None,
) -> "EstimatedCoverageResponseDTO":
    """§81 — 세션의 측정점들을 GP regression 으로 dense map 추정.

    method:
      - 'auto':            sim 있으면 residual_kriging, 없으면 gp_only
      - 'gp_only':         측정값만 GP — "실측 히트맵" 의미. sim 안 섞임
      - 'residual_kriging': sim 을 prior 로 residual GP — "통합 분석" 의미.
                            sim 없으면 gp_only 로 fallback (안전망)

    프론트엔드의 '실측 히트맵' 탭은 gp_only, '예측·실측 통합 분석' 탭은
    residual_kriging 를 명시적으로 호출 → 라벨과 의미 일치.
    """
    # lazy import — 무거운 sklearn / matplotlib 을 모듈 import 단에서 끌어오지 않음
    import numpy as np

    from app.schemas.rf.measurement import (
        EstimatedCoverageResponseDTO,
        EstimatedRssiRangeDTO,
    )
    from app.services._s3 import presigned_get_url
    from app.services.rf.measurement_estimation.gp_estimator import (
        estimate_coverage,
        estimate_coverage_residual,
    )
    from app.services.rf.measurement_estimation.heatmap import render_and_upload

    session_row = _load_owned_session(db, session_id, user)

    # 측정점 (rssi 있는 것만) 로드
    filters = [
        MeasurementPoint.session_id == session_row.id,
        MeasurementPoint.rssi_dbm.isnot(None),
    ]
    if ap_bssid:
        filters.append(func.lower(MeasurementPoint.ap_bssid) == ap_bssid.lower())
    rows = db.execute(select(MeasurementPoint).where(*filters)).scalars().all()

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

    # bounds — confirmed scene 의 벽/개구부 bbox 우선 (프론트 캔버스가 이 좌표계로 도면을 그림).
    # 도면 이미지 픽셀 bounds 는 scene 좌표계와 어긋날 수 있어 후순위.
    bounds_dto = _bounds_from_scene_walls(db, session_row.scene_version_id)
    if bounds_dto is None:
        floorplan = _floorplan_info_from_asset(db, session_row.asset_id)
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

    # method 분기:
    #   - gp_only:           sim 무시, 측정값만 GP (실측 의미 정직)
    #   - residual_kriging:  sim prior + residual GP (sim 없으면 gp_only 로 fallback)
    #   - auto:              sim 있으면 residual, 없으면 gp_only
    estimate = None
    want_residual = method in ("residual_kriging", "auto")
    if want_residual:
        sim_grid_data = _try_load_sim_grid_for_scene(
            db, str(session_row.floor_id), session_row.scene_version_id
        )
        if sim_grid_data is not None:
            sim_grid, sim_xs, sim_ys = sim_grid_data
            try:
                estimate = estimate_coverage_residual(
                    points, sim_grid=sim_grid, sim_xs=sim_xs, sim_ys=sim_ys,
                )
            except ValueError as exc:
                # 측정점 다 sim bounds 밖이면 fallback (sim 없는 거나 마찬가지).
                import logging
                logging.getLogger(__name__).info(
                    "Residual kriging skipped (%s) — falling back to pure GP", exc,
                )
                estimate = None

    if estimate is None:
        estimate = estimate_coverage(
            points, bounds=bounds_tuple, grid_resolution_m=grid_resolution_m
        )

    # heatmap 생성 + S3
    mean_uri, std_uri = render_and_upload(estimate, str(session_row.id), points)

    # rssi_range: frontend Legend/점 색 그라데이션이 이 값으로 색 스케일을 잡음.
    # raw min/max 는 sim invalid 셀 (-200 이하 sentinel) 로 오염될 수 있어 그대로 쓰면
    # 그라데이션이 "-263 · -154 · -45" 같은 비현실 값 표시 + 색이 한쪽으로 쏠림.
    # → noise floor 이상 + 비유한값 제외한 셀 들로만 계산.
    grid = estimate.mean_grid
    finite_mask = np.isfinite(grid) & (grid > -120.0)
    coverage_threshold_dbm = -67.0
    coverage_ratio = None
    coverage_score = None
    average_rssi_dbm = None
    bottom_10_percent_rssi_dbm = None
    if finite_mask.any():
        valid = grid[finite_mask]
        # p2~p98 percentile — 양 극단 outlier (정상 범위지만 1~2 셀만 튀는 값) 도 제외.
        lo, hi = np.percentile(valid, [2.0, 98.0])
        rmin, rmax, rmean = float(lo), float(hi), float(valid.mean())
        coverage_ratio = float(np.mean(valid >= coverage_threshold_dbm))
        coverage_score = coverage_ratio
        average_rssi_dbm = rmean
        bottom_10_percent_rssi_dbm = float(np.percentile(valid, 10.0))
    else:
        rmin, rmax, rmean = -90.0, -30.0, -60.0  # fallback
    return EstimatedCoverageResponseDTO(
        heatmap_url=presigned_get_url(mean_uri),
        uncertainty_url=presigned_get_url(std_uri),
        bounds=bounds_dto,
        grid_shape=list(estimate.mean_grid.shape),
        grid_resolution_m=grid_resolution_m,
        rssi_range=EstimatedRssiRangeDTO(min=rmin, max=rmax, mean=rmean),
        uncertainty_max_db=float(estimate.std_grid.max()),
        input_point_count=estimate.input_point_count,
        kernel_repr=estimate.kernel_repr,
        method=estimate.method,
        coverage_threshold_dbm=coverage_threshold_dbm,
        coverage_ratio=coverage_ratio,
        coverage_score=coverage_score,
        average_rssi_dbm=average_rssi_dbm,
        bottom_10_percent_rssi_dbm=bottom_10_percent_rssi_dbm,
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
