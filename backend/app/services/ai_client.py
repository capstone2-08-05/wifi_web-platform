import logging
import requests
import uuid
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.core.settings import ai_service_url

logger = logging.getLogger(__name__)

class AIApiClient:
    def __init__(self):
        self.base_url = ai_service_url()

    def fetch_ai_inference(self, image_bytes: bytes, filename: str) -> dict[str, Any]:
        if not self.base_url:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "AI_SERVICE_URL not set. Connect external AI repo server.",
                503,
            )

        file_id = str(uuid.uuid4())

        files = {"file": (filename, image_bytes)}
        data = {"file_id": file_id}

        try:
            unet_url = f"{self.base_url}/inference/unet"
            unet_res = requests.post(unet_url, files=files, data=data, timeout=300.0)
            unet_res.raise_for_status()

            yolo_url = f"{self.base_url}/inference/yolo"
            yolo_res = requests.post(yolo_url, files=files, data=data, timeout=300.0)
            yolo_res.raise_for_status()

            return {
                "unet": unet_res.json(),
                "yolo": yolo_res.json(),
            }
        except requests.RequestException as exc:
            logger.exception("AI inference request failed")
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"AI inference request failed: {exc}",
                502,
            ) from exc

ai_client = AIApiClient()