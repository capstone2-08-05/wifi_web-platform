import logging
import asyncio
import uuid
from typing import Any

import httpx

from app.core.errors import AppError, ErrorCode
from app.core.settings import ai_service_url

logger = logging.getLogger(__name__)

class AIApiClient:
    def __init__(self):
        self.base_url = ai_service_url()

    async def fetch_ai_inference_async(self, image_bytes: bytes, filename: str) -> dict[str, Any]:
        if not self.base_url:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "AI_SERVICE_URL not set. Connect external AI repo server.",
                503,
            )

        file_id = str(uuid.uuid4())

        async def _post_inference(client: httpx.AsyncClient, route: str) -> dict[str, Any]:
            response = await client.post(
                f"{self.base_url}/{route}",
                data={"file_id": file_id},
                files={"file": (filename, image_bytes)},
            )
            response.raise_for_status()
            return response.json()

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                unet_res, yolo_res = await asyncio.gather(
                    _post_inference(client, "inference/unet"),
                    _post_inference(client, "inference/yolo"),
                )

            return {
                "unet": unet_res,
                "yolo": yolo_res,
            }
        except httpx.HTTPError as exc:
            logger.exception("Async AI inference request failed")
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"AI inference request failed: {exc}",
                502,
            ) from exc

ai_client = AIApiClient()