import uuid
from app.api.deps import get_current_user
from app.models.user import User
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.settings import UPLOAD_DIR
from app.db.session import get_db
from app.schemas.scene_draft import (
    SaveSceneDraftRequestDTO,
    UploadStorageMetadataDTO,
)
from app.services.fusion_service import fusion_service
from app.services.scene_draft_service import _resolve_project_floor, save_scene_draft

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


def _validate_and_save_file(file: UploadFile, content: bytes) -> tuple[str, Path]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AppError(
            ErrorCode.INVALID_FILE_EXTENSION,
            "Only png/jpg/jpeg/pdf are allowed.",
            400,
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"

    try:
        save_path.write_bytes(content)
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_SAVE_FAILED,
            f"Failed to save uploaded file: {exc}",
            500,
        ) from exc

    return file_id, save_path


@router.post("/floorplan")
async def upload_floorplan(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    file_id, save_path = _validate_and_save_file(file, content)

    return {
        "status": "ok",
        "fileId": file_id,
        "filename": file.filename,
        "contentType": file.content_type,
        "size": len(content),
        "savedPath": str(save_path),
    }


@router.post("/floorplan/analyze")
async def upload_and_analyze_floorplan(
    file: UploadFile = File(...),
    real_width_m: float = Form(10.0),
    project_id: str | None = Form(None),
    floor_id: str | None = Form(None),
    created_by: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    content = await file.read()
    file_id, save_path = _validate_and_save_file(file, content)

    # SageMaker invoke 는 project_id/floor_id 기반 S3 경로를 사용하므로
    # default project/floor 로 먼저 해소 (scene_draft_service 와 동일 로직 재사용)
    resolved_project_id, resolved_floor_id = _resolve_project_floor(
        db, project_id, floor_id, current_user
    )

    try:
        scene = await fusion_service.process_image_to_scene_async(
            image_bytes=content,
            filename=file.filename or f"{file_id}",
            real_width_m=real_width_m,
            project_id=resolved_project_id,
            floor_id=resolved_floor_id,
            content_type=file.content_type or "application/octet-stream",
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            ErrorCode.INTERNAL_SERVER_ERROR,
            f"Floorplan analysis failed: {exc}",
            500,
        ) from exc

    request_dto = SaveSceneDraftRequestDTO(
        scene=scene,
        upload=UploadStorageMetadataDTO(
            provider="local",
            original_filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(content),
            local_saved_path=str(save_path),
        ),
        project_id=resolved_project_id,
        floor_id=resolved_floor_id,
        created_by=created_by,
    )

    result = save_scene_draft(db, request_dto, current_user)

    return {
        "status": "ok",
        "scene_draft_id": result.scene_draft_id,
        "fileId": file_id,
        "savedPath": str(save_path),
        "scene": scene.model_dump(),
    }