
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AssetType
from app.core.errors import AppError, ErrorCode
from app.models.asset import Asset
from app.models.floor import Floor
from app.models.project import Project
from app.models.user import User
from app.services import _local_storage as _storage

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
# Storage key 빌더 (이전엔 S3 key. 지금은 local://{key} 형태로 보관)
# ---------------------------------------------------------------------------
def _build_storage_key(
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

    # 3. 본문 읽기 + 로컬 저장
    asset_id = uuid4()
    key = _build_storage_key(project.id, floor.id, asset_id, ext)
    mime_type = ALLOWED_EXTENSIONS[ext]
    try:
        body = upload.file.read()
    finally:
        upload.file.close()
    storage_uri = _storage.upload_bytes(key, body, content_type=mime_type)

    # 4. DB row 생성
    asset = Asset(
        id=str(asset_id),
        project_id=project.id,
        floor_id=floor.id,
        uploaded_by=user.id,
        asset_type=asset_type,
        source_format=ext,
        storage_url=storage_uri,
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
        # DB 실패 시 업로드된 파일 정리
        _storage.delete_object(storage_uri)
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
    """이미 byte 로 읽어둔 도면 이미지를 로컬 저장소 + assets 에 저장.

    /upload/floorplan/analyze 흐름처럼 UploadFile 을 한 번 read 한 뒤 같은 byte 를
    ai_api 호출과 asset 양쪽에 써야 할 때 사용한다. commit 은 호출자에게 위임
    (보통 같은 트랜잭션에서 Job row 도 같이 commit).
    """
    asset_type = AssetType.FLOORPLAN_IMAGE.value
    ext = _resolve_extension(filename)
    asset_id = uuid4()
    key = _build_storage_key(project_id, floor_id, asset_id, ext)
    mime_type = content_type or ALLOWED_EXTENSIONS[ext]
    storage_uri = _storage.upload_bytes(key, content, content_type=mime_type)

    asset = Asset(
        id=str(asset_id),
        project_id=project_id,
        floor_id=floor_id,
        uploaded_by=uploaded_by,
        asset_type=asset_type,
        source_format=ext,
        storage_url=storage_uri,
        mime_type=mime_type,
        file_size_bytes=len(content),
        metadata_json={},
    )
    try:
        db.add(asset)
        db.flush()
    except Exception:
        db.rollback()
        _storage.delete_object(storage_uri)
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
    """다운로드 URL + 만료 초 반환. 로컬 저장소는 만료 개념 없어 0 반환."""
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    if not asset.storage_url:
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset storage_url missing.",
            status_code=404,
        )
    # 로컬 저장소: 영구 URL
    if _storage.is_local_uri(asset.storage_url):
        return _storage.static_url(asset.storage_url), 0
    # 구 데이터 (s3://) 는 외부에서 못 푸므로 404 — 회귀 시 _s3.presigned_get_url 로 부활
    raise AppError(
        ErrorCode.UPLOADED_FILE_NOT_FOUND,
        "Asset is on legacy storage (s3://) — AWS path is disabled.",
        status_code=404,
    )


def delete_asset(db: Session, asset_id: UUID, user: User) -> None:
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    storage_uri = asset.storage_url if asset.storage_url else None

    # 파일 먼저 — 실패해도 DB 삭제는 진행 (idempotent).
    if storage_uri:
        try:
            _storage.delete_object(storage_uri)
        except AppError:
            pass

    try:
        db.delete(asset)
        db.commit()
    except Exception:
        db.rollback()
        raise
