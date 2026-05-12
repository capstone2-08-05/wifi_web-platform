
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.settings import ASSETS_DIR
from app.models.asset import Asset
from app.models.floor import Floor
from app.models.project import Project
from app.models.user import User

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
# 파일 저장 헬퍼
# ---------------------------------------------------------------------------
def _build_storage_path(
    project_id: str, floor_id: str, asset_id: UUID, ext: str
) -> Path:
    return Path(ASSETS_DIR) / str(project_id) / str(floor_id) / f"{asset_id}.{ext}"


def _save_upload_to_disk(upload: UploadFile, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
    except OSError as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise AppError(
            code=ErrorCode.FILE_STORAGE_ERROR,
            message=f"Failed to save file: {e}",
            status_code=500,
        ) from e
    finally:
        upload.file.close()
    return dest.stat().st_size


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

    # 3. 디스크 저장
    asset_id = uuid4()
    storage_path = _build_storage_path(project.id, floor.id, asset_id, ext)
    file_size = _save_upload_to_disk(upload, storage_path)

    # 4. DB row 생성
    mime_type = ALLOWED_EXTENSIONS[ext]
    asset = Asset(
        id=str(asset_id),
        project_id=project.id,
        floor_id=floor.id,
        uploaded_by=user.id,
        asset_type=asset_type,
        source_format=ext,
        storage_url=str(storage_path),
        mime_type=mime_type,
        file_size_bytes=file_size,
        metadata_json={},
    )
    try:
        db.add(asset)
        db.commit()
        db.refresh(asset)
    except Exception:
        db.rollback()
        if storage_path.exists():
            storage_path.unlink(missing_ok=True)
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


def delete_asset(db: Session, asset_id: UUID, user: User) -> None:
    asset, _floor, _project = _get_owned_asset_or_404(db, asset_id, user)

    storage_path = Path(asset.storage_url) if asset.storage_url else None

    try:
        db.delete(asset)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if storage_path is not None and storage_path.exists():
        try:
            storage_path.unlink()
        except OSError:
            pass