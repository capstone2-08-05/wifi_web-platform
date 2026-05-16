
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

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

ALLOWED_ASSET_TYPES: set[str] = {"floorplan", "photo", "document"}


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
    """presigned GET URL + 만료 초 반환."""
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)
    if not asset.storage_url or not asset.storage_url.startswith("s3://"):
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            "Asset is not on S3 (legacy local path).",
            status_code=404,
        )
    url = _s3.presigned_get_url(
        asset.storage_url, expires_seconds=RF_PRESIGNED_URL_EXPIRES_SECONDS
    )
    return url, RF_PRESIGNED_URL_EXPIRES_SECONDS


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
