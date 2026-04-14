import uuid
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from app.core.settings import UPLOAD_DIR
from app.services.fusion_service import fusion_service
from app.schemas.floorplan import SceneSchema

router = APIRouter(prefix="/space", tags=["space"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

@router.post("/analyze", response_model=SceneSchema)
async def analyze_floorplan(
    file: UploadFile = File(...),
    real_width: float = Form(..., description="도면의 실제 가로 길이 (미터 단위)")
) -> SceneSchema:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="PNG, JPG, JPEG 파일만 지원합니다.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"

    content = await file.read()
    with save_path.open("wb") as f:
        f.write(content)

    try:
        
        result_scene = fusion_service.process_image_to_scene(
            image_bytes=content,
            filename=file.filename,
            real_width_m=real_width
        )
        
        return result_scene

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"도면 분석 중 오류 발생: {str(exc)}")