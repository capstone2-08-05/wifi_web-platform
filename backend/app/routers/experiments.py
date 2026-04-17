from pathlib import Path
import mimetypes

import requests
from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode
from app.core.settings import UPLOAD_DIR, ai_service_url, rf_server_url
from app.services.wall_extraction import run_rule_based_wall_extraction

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("/wall/rule-based/{file_id}")
def wall_rule_based(file_id: str) -> dict:
    image_path = _find_uploaded_file(file_id)
    if image_path is None:
        raise AppError(ErrorCode.UPLOADED_FILE_NOT_FOUND, "Uploaded file not found.", 404)

    try:
        mask_path = run_rule_based_wall_extraction(image_path)
        return {
            "status": "ok",
            "fileId": file_id,
            "walls": mask_path,
        }
    except Exception as exc:
        raise AppError(
            ErrorCode.WALL_EXTRACTION_FAILED,
            f"Wall extraction failed: {exc}",
            500,
        ) from exc


@router.post("/wall/unet/{file_id}")
def wall_unet(file_id: str) -> dict:
    service = ai_service_url()
    if not service:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AI_SERVICE_URL not set. Connect external AI repo server.",
            503,
        )

    image_path = _find_uploaded_file(file_id)
    if image_path is None:
        raise AppError(ErrorCode.UPLOADED_FILE_NOT_FOUND, "Uploaded file not found.", 404)

    return _send_file_to_ai(
        f"{service.rstrip('/')}/inference/unet",
        file_id=file_id,
        image_path=image_path,
        timeout=120,
    )


@router.post("/objects/yolo/{file_id}")
def objects_yolo(file_id: str) -> dict:
    service = ai_service_url()
    if not service:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AI_SERVICE_URL not set. Connect external AI repo server.",
            503,
        )

    image_path = _find_uploaded_file(file_id)
    if image_path is None:
        raise AppError(ErrorCode.UPLOADED_FILE_NOT_FOUND, "Uploaded file not found.", 404)

    return _send_file_to_ai(
        f"{service.rstrip('/')}/inference/yolo",
        file_id=file_id,
        image_path=image_path,
        timeout=120,
    )


@router.post("/rf/sionna/smoke")
def rf_sionna_smoke() -> dict:
    service = rf_server_url()
    if not service:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "RF_SERVER_URL not set. Connect external RF repo server.",
            503,
        )

    try:
        response = requests.post(f"{service.rstrip('/')}/sionna/smoke", timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"RF service request failed: {exc}",
            502,
        ) from exc


def _find_uploaded_file(file_id: str) -> Path | None:
    if not UPLOAD_DIR.exists():
        return None
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    return matches[0] if matches else None


def _send_file_to_ai(endpoint: str, file_id: str, image_path: Path, timeout: int) -> dict:
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    try:
        with image_path.open("rb") as f:
            response = requests.post(
                endpoint,
                data={"file_id": file_id},
                files={"file": (image_path.name, f, content_type)},
                timeout=timeout,
            )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"AI service request failed: {exc}",
            502,
        ) from exc
