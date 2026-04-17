import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.settings import UPLOAD_DIR
from app.db.session import get_db
from app.schemas.scene_draft import SaveSceneDraftRequestDTO, UploadStorageMetadataDTO
from app.services.fusion_service import fusion_service
from app.schemas.scene import SceneSchema
from app.services.scene_draft_service import save_scene_draft

router = APIRouter(prefix="/space", tags=["space"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

@router.post("/analyze", response_model=SceneSchema)
async def analyze_floorplan(
    file: UploadFile = File(...),
    real_width: float = Form(..., description="도면의 실제 가로 길이 (미터 단위)"),
    project_id: str | None = Form(default=None),
    floor_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> SceneSchema:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AppError(
            ErrorCode.INVALID_FILE_EXTENSION,
            "Only PNG, JPG, JPEG are supported.",
            400,
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"

    content = await file.read()
    try:
        with save_path.open("wb") as f:
            f.write(content)
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_SAVE_FAILED,
            f"Failed to save uploaded file: {exc}",
            500,
        ) from exc

    result_scene = await fusion_service.process_image_to_scene_async(
        image_bytes=content,
        filename=file.filename,
        real_width_m=real_width,
    )

    save_result = save_scene_draft(
        db,
        SaveSceneDraftRequestDTO(
            scene=result_scene,
            upload=UploadStorageMetadataDTO(
                provider="local",
                original_filename=file.filename,
                content_type=file.content_type,
                size_bytes=len(content),
                local_saved_path=str(save_path),
            ),
            project_id=project_id,
            floor_id=floor_id,
        ),
    )
    result_scene.scene_draft_id = save_result.scene_draft_id

    return result_scene