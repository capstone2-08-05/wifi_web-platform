import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.settings import UPLOAD_DIR

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}


@router.post("/floorplan")
async def upload_floorplan(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only png/jpg/jpeg/pdf are allowed")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"

    with save_path.open("wb") as f:
        content = await file.read()
        f.write(content)

    return {
        "status": "ok",
        "fileId": file_id,
        "filename": file.filename,
        "contentType": file.content_type,
        "size": len(content),
        "savedPath": str(save_path),
    }
