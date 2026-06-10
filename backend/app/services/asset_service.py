
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetType
from app.core.errors import AppError, ErrorCode
from app.core.settings import RF_PRESIGNED_URL_EXPIRES_SECONDS
from app.models.asset import Asset
from app.models.floor import Floor
from app.models.project import Project
from app.models.user import User
from app.services import _s3

ALLOWED_EXTENSIONS: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
}

# AssetType enum 과 1:1 매칭. measurement_service._latest_floorplan_asset 가
# Asset.asset_type == "floorplan_image" 로 검색하므로 같은 문자열을 강제한다.
# 새 종류(photo/document 등)는 먼저 AssetType enum 에 추가해야 함.
ALLOWED_ASSET_TYPES: set[str] = {t.value for t in AssetType}


# ---------------------------------------------------------------------------
# 권한 체크 헬퍼
# ---------------------------------------------------------------------------
def _get_owned_floor_or_404(
    db: Session, floor_id: UUID, user: User
) -> tuple[Floor, Project]:
    stmt = (
        select(Floor, Project)
        .join(Project, Floor.project_id == Project.id)
        .where(Floor.id == str(floor_id), Project.owner_user_id == user.id)
    )
    row = db.execute(stmt).first()
    if row is None:
        raise AppError(
            code=ErrorCode.FLOOR_NOT_FOUND,
            message="Floor not found",
            status_code=404,
        )
    floor, project = row
    return floor, project


def _get_owned_asset_or_404(
    db: Session, asset_id: UUID, user: User
) -> tuple[Asset, Floor, Project]:
    """본인 소유 asset 만 반환. 아니면 404."""
    stmt = (
        select(Asset, Floor, Project)
        .join(Floor, Asset.floor_id == Floor.id)
        .join(Project, Floor.project_id == Project.id)
        .where(Asset.id == str(asset_id), Project.owner_user_id == user.id)
    )
    row = db.execute(stmt).first()
    if row is None:
        raise AppError(
            code=ErrorCode.ASSET_NOT_FOUND,
            message="Asset not found",
            status_code=404,
        )
    asset, floor, project = row
    return asset, floor, project


# ---------------------------------------------------------------------------
# 검증 헬퍼
# ---------------------------------------------------------------------------
def _resolve_extension(filename: Optional[str]) -> str:
    if not filename:
        raise AppError(
            code=ErrorCode.INVALID_FILE_EXTENSION,
            message="Filename is required",
            status_code=400,
        )
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError(
            code=ErrorCode.INVALID_FILE_EXTENSION,
            message=(
                f"Unsupported file extension: .{ext}. "
                f"Allowed: {sorted(ALLOWED_EXTENSIONS.keys())}"
            ),
            status_code=400,
        )
    return ext


def _validate_asset_type(asset_type: str) -> str:
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise AppError(
            code=ErrorCode.INVALID_ASSET_TYPE,
            message=(
                f"Unsupported asset_type: {asset_type}. "
                f"Allowed: {sorted(ALLOWED_ASSET_TYPES)}"
            ),
            status_code=400,
        )
    return asset_type


# ---------------------------------------------------------------------------
# S3 키 빌더
# ---------------------------------------------------------------------------
def _build_s3_key(
    project_id: str, floor_id: str, asset_id: UUID, ext: str
) -> str:
    return f"assets/{project_id}/{floor_id}/{asset_id}.{ext}"


# ---------------------------------------------------------------------------
# 퍼블릭 API
# ---------------------------------------------------------------------------
def create_asset(
    db: Session,
    floor_id: UUID,
    asset_type: str,
    upload: UploadFile,
    user: User,
) -> Asset:
    # 1. 검증
    _validate_asset_type(asset_type)
    ext = _resolve_extension(upload.filename)

    # 2. 권한 체크 (project_id 확보)
    floor, project = _get_owned_floor_or_404(db, floor_id, user)

    # 3. 본문 읽기 + S3 업로드
    asset_id = uuid4()
    key = _build_s3_key(project.id, floor.id, asset_id, ext)
    mime_type = ALLOWED_EXTENSIONS[ext]
    try:
        body = upload.file.read()
    finally:
        upload.file.close()
    s3_uri = _s3.upload_bytes(key, body, content_type=mime_type)

    # 4. DB row 생성
    asset = Asset(
        id=str(asset_id),
        project_id=project.id,
        floor_id=floor.id,
        uploaded_by=user.id,
        asset_type=asset_type,
        source_format=ext,
        storage_url=s3_uri,
        mime_type=mime_type,
        file_size_bytes=len(body),
        metadata_json={},
    )
    try:
        db.add(asset)
        db.commit()
        db.refresh(asset)
    except Exception:
        db.rollback()
        # DB 실패 시 업로드된 S3 객체 정리
        _s3.delete_object(s3_uri)
        raise

    return asset


def create_floorplan_asset_from_bytes(
    db: Session,
    *,
    project_id: str,
    floor_id: str,
    content: bytes,
    filename: str,
    content_type: Optional[str],
    uploaded_by: str,
) -> Asset:
    """이미 byte 로 읽어둔 도면 이미지를 S3 + assets 에 저장.

    /upload/floorplan/analyze 흐름처럼 UploadFile 을 한 번 read 한 뒤 같은 byte 를
    SageMaker 와 asset 양쪽에 써야 할 때 사용한다. commit 은 호출자에게 위임
    (보통 같은 트랜잭션에서 Job row 도 같이 commit).
    """
    asset_type = AssetType.FLOORPLAN_IMAGE.value
    ext = _resolve_extension(filename)
    asset_id = uuid4()
    key = _build_s3_key(project_id, floor_id, asset_id, ext)
    mime_type = content_type or ALLOWED_EXTENSIONS[ext]
    s3_uri = _s3.upload_bytes(key, content, content_type=mime_type)

    asset = Asset(
        id=str(asset_id),
        project_id=project_id,
        floor_id=floor_id,
        uploaded_by=uploaded_by,
        asset_type=asset_type,
        source_format=ext,
        storage_url=s3_uri,
        mime_type=mime_type,
        file_size_bytes=len(content),
        metadata_json={},
    )
    try:
        db.add(asset)
        db.flush()
    except Exception:
        db.rollback()
        _s3.delete_object(s3_uri)
        raise
    return asset


def create_floorplan_asset_from_local_path(
    db: Session,
    *,
    project_id: str,
    floor_id: str,
    local_path: str,
    filename: str,
    content_type: Optional[str],
    file_size_bytes: int,
    uploaded_by: str,
) -> Asset:
    """로컬 FS 에 이미 저장된 도면 이미지를 assets 에 등록 (S3 업로드 없음).

    로컬 추론 모드(`/upload/floorplan/analyze?inference_mode=local`) 전용. router 의
    `_validate_and_save_file` 가 이미 UPLOAD_DIR 에 파일을 저장했으므로, 그 경로를
    그대로 `storage_url = file:///abs/path` 로 보관해서 DB row 만든다.

    `/assets/{id}/download-url` 은 `file://` 스킴을 감지해 백엔드 자체 스트리밍
    엔드포인트(`/assets/{id}/raw`) URL 을 반환한다 (S3 presigned 우회).
    """
    asset_type = AssetType.FLOORPLAN_IMAGE.value
    ext = _resolve_extension(filename)
    mime_type = content_type or ALLOWED_EXTENSIONS[ext]
    asset_id = uuid4()

    # 경로 정규화 + file:// URI 로 보관 (드라이브 표기 윈도우 호환).
    abs_path = Path(local_path).resolve()
    storage_url = abs_path.as_uri()  # 예: file:///C:/capstone2/.../uploads/xxx.jpg

    asset = Asset(
        id=str(asset_id),
        project_id=project_id,
        floor_id=floor_id,
        uploaded_by=uploaded_by,
        asset_type=asset_type,
        source_format=ext,
        storage_url=storage_url,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        metadata_json={},
    )
    try:
        db.add(asset)
        db.flush()
    except Exception:
        db.rollback()
        raise
    return asset


def list_assets(
    db: Session,
    floor_id: UUID,
    user: User,
    asset_type: Optional[str] = None,
) -> list[Asset]:
    _get_owned_floor_or_404(db, floor_id, user)

    stmt = select(Asset).where(Asset.floor_id == str(floor_id))
    if asset_type is not None:
        _validate_asset_type(asset_type)
        stmt = stmt.where(Asset.asset_type == asset_type)
    stmt = stmt.order_by(Asset.created_at.desc())

    return list(db.execute(stmt).scalars().all())


def get_asset(db: Session, asset_id: UUID, user: User) -> Asset:
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    return asset


def get_asset_download_url(
    db: Session, asset_id: UUID, user: User
) -> tuple[str, int]:
    """asset 다운로드 URL + 만료 초 반환.

    - `s3://` 자산: S3 presigned GET URL
    - `file://` 자산 (로컬 추론 모드): 백엔드 자체 스트리밍 엔드포인트 상대 경로
    """
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    url_value = asset.storage_url or ""
    if url_value.startswith("s3://"):
        url = _s3.presigned_get_url(
            url_value, expires_seconds=RF_PRESIGNED_URL_EXPIRES_SECONDS
        )
        return url, RF_PRESIGNED_URL_EXPIRES_SECONDS
    if url_value.startswith("file://"):
        # 백엔드가 자체 스트리밍 — 만료 개념 없지만 client 호환성을 위해 0 으로.
        return f"/assets/{asset.id}/raw", 0
    raise AppError(
        ErrorCode.UPLOADED_FILE_NOT_FOUND,
        f"Asset has unsupported storage scheme: {url_value[:40]}",
        status_code=404,
    )


def open_asset_local_file(
    db: Session, asset_id: UUID, user: User
) -> tuple[Path, str]:
    """`file://` 자산의 로컬 파일 경로 + mime_type 반환. 스트리밍 endpoint 가 사용.

    권한 체크(_get_owned_asset_or_404) 포함. S3 자산이면 404.
    """
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    url_value = asset.storage_url or ""
    if not url_value.startswith("file://"):
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset is not a local file.",
            status_code=404,
        )
    # file:///C:/path → Path 추출. Path.from_uri 는 3.13+, urlparse 로 호환.
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url_value)
    raw_path = unquote(parsed.path)
    # 윈도우: '/C:/x/y' 형태 → 앞의 '/' 제거
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Local asset file missing on disk: {path}",
            status_code=404,
        )
    return path, asset.mime_type or "application/octet-stream"


def open_asset_local_file_public(
    db: Session, asset_id: UUID
) -> tuple[Path, str]:
    """`file://` 자산 스트리밍 — 인증 없이 UUID로만 조회. /raw 엔드포인트 전용."""
    from urllib.parse import urlparse, unquote
    asset = db.get(Asset, asset_id)
    if not asset:
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset not found.",
            status_code=404,
        )
    url_value = asset.storage_url or ""
    if not url_value.startswith("file://"):
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset is not a local file.",
            status_code=404,
        )
    parsed = urlparse(url_value)
    raw_path = unquote(parsed.path)
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Local asset file missing on disk: {path}",
            status_code=404,
        )
    return path, asset.mime_type or "application/octet-stream"


def delete_asset(db: Session, asset_id: UUID, user: User) -> None:
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    s3_uri = asset.storage_url if asset.storage_url else None

    # S3 먼저 — 실패 시 (예: AccessDenied) DB 행 유지해서 재시도 가능.
    # 성공 시 idempotent (S3 객체 없어도 200) 라 DB 만 남은 상태에서도 안전.
    if s3_uri and s3_uri.startswith("s3://"):
        _s3.delete_object(s3_uri)

    try:
        db.delete(asset)
        db.commit()
    except Exception:
        db.rollback()
        raise
