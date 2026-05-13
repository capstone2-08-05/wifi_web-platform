import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError, ErrorCode
from app.core.settings import UPLOAD_DIR
from app.db.session import get_db
from app.models.user import User
from app.schemas.scene_draft import UploadStorageMetadataDTO
from app.services.floorplan_job_service import submit_floorplan_analysis

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


@router.post(
    "/floorplan/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    summary="도면 분석 Job 등록 (비동기). job_id 받아서 GET /floorplan-jobs/{job_id} 로 폴링.",
)
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

    upload_metadata = UploadStorageMetadataDTO(
        provider="local",
        original_filename=file.filename,
        content_type=file.content_type,
        size_bytes=len(content),
        local_saved_path=str(save_path),
    )

    job = await submit_floorplan_analysis(
        db,
        image_bytes=content,
        filename=file.filename or f"{file_id}",
        content_type=file.content_type or "application/octet-stream",
        real_width_m=real_width_m,
        project_id=project_id,
        floor_id=floor_id,
        current_user=current_user,
        upload_metadata=upload_metadata,
        created_by=created_by,
    )

    return {
        "status": "submitted",
        "job_id": job.id,
        "project_id": job.project_id,
        "floor_id": job.floor_id,
        "job_status": job.status,
        "sagemaker_inference_id": (job.input_json or {}).get("sagemaker", {}).get("inference_id"),
        "fileId": file_id,
        "savedPath": str(save_path),
        "poll_url": f"/floorplan-jobs/{job.id}",
    }
