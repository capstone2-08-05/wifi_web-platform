from pathlib import Path
import mimetypes
import shutil
import tempfile
import uuid

import requests
from fastapi import APIRouter, File, Form, UploadFile

from app.core.errors import AppError, ErrorCode
from app.core.settings import MASK_DIR, UPLOAD_DIR, ai_service_url, rf_server_url
from app.services.wall_extraction import run_rule_based_wall_extraction, wall_extractor

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


@router.post("/wall/postprocess/{file_id}")
async def wall_postprocess(
    file_id: str,
    prob_map: UploadFile = File(..., description="U-Net wall probability map (.npy)"),
    threshold: float | None = Form(
        None,
        description="명시하면 adaptive scoring 건너뛰고 그 값 사용 (디버깅용).",
    ),
) -> dict:
    """§69 wall postprocess 디버깅 — adaptive threshold scoring 결과를 그대로 dump.

    `file_id` 의 업로드된 원본 도면 이미지를 OCR/선분 검출 입력으로 쓰고,
    multipart 로 받은 prob_map .npy 를 후처리 파이프라인에 통과시킴.
    응답에 후보별 점수와 디버그 이미지 디렉토리가 포함되어 전/후 비교 가능.
    """
    image_path = _find_uploaded_file(file_id)
    if image_path is None:
        raise AppError(ErrorCode.UPLOADED_FILE_NOT_FOUND, "Uploaded file not found.", 404)

    # multipart .npy → temp 파일로 저장 (numpy.load 가 파일 경로 필요).
    tmp_dir = Path(tempfile.mkdtemp(prefix="wall_pp_"))
    tmp_npy = tmp_dir / "prob_map.npy"
    try:
        with tmp_npy.open("wb") as f:
            shutil.copyfileobj(prob_map.file, f)

        run_id = uuid.uuid4().hex[:12]
        debug_dir = MASK_DIR / "wall_postprocess" / f"debug_{file_id}_{run_id}"

        try:
            result = wall_extractor.execute_from_prob_map(
                tmp_npy,
                threshold=threshold,
                detections=None,
                image_path=image_path,
                debug_dir=debug_dir,
            )
        except Exception as exc:
            raise AppError(
                ErrorCode.WALL_EXTRACTION_FAILED,
                f"Wall postprocess failed: {exc}",
                500,
            ) from exc

        return {
            "status": "ok",
            "fileId": file_id,
            "walls": result.walls,
            "postprocess_metadata": result.postprocess.to_dict(),
        }
    finally:
        # .npy 파일만 정리. 디버그 이미지 (debug_dir) 는 의도적으로 남김.
        try:
            tmp_npy.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


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
