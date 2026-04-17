import httpx

from fastapi import APIRouter

from app.core.errors import AppError, ErrorCode
from app.core.settings import ai_service_url
from app.schemas.scene import SceneSchema

router = APIRouter(prefix="/rf", tags=["rf"])

@router.post("/run")
async def run_rf_simulation(body: SceneSchema):
    service = ai_service_url()
    if not service:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AI_SERVICE_URL not set. Connect external AI repo server.",
            503,
        )

    async with httpx.AsyncClient() as client:
        all_data = body.model_dump()
        config = all_data.pop("config")
        antenna = all_data.pop("antenna")

        payload = {
            "engine": "sionna_rt",
            "run_type": "run",
            "floor_id": None,
            "input": {
                "kind": "sionna_dto",
                "data": {
                    "config": config,
                    "antenna": antenna,
                    "scene": all_data,
                },
            },
        }

        target_url = f"{service.rstrip('/')}/internal/sionna/run"

        try:
            response = await client.post(
                target_url,
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise AppError(
                ErrorCode.RF_SIMULATION_FAILED,
                f"RF simulation failed with status {exc.response.status_code}: {exc.response.text}",
                502,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"AI server request failed: {exc}",
                502,
            ) from exc