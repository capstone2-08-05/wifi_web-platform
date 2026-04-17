import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from app.core.errors import AppError, ErrorCode
from app.core.settings import UPLOAD_DIR

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


@router.post("/floorplan")
async def upload_floorplan(file: UploadFile = File(...)) -> dict:
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
        with save_path.open("wb") as f:
            content = await file.read()
            f.write(content)
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_SAVE_FAILED,
            f"Failed to save uploaded file: {exc}",
            500,
        ) from exc

    return {
        "status": "ok",
        "fileId": file_id,
        "filename": file.filename,
        "contentType": file.content_type,
        "size": len(content),
        "savedPath": str(save_path),
    }
