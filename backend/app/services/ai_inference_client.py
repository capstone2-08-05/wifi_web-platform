"""ai_api HTTP 클라이언트 (SageMaker 대체).

ai_api 는 친구 로컬 GPU 또는 Colab T4 위에서 떠있는 FastAPI 서버. 3 개 라우트:
  - POST /inference/unet           — multipart, UNet 벽 segmentation
  - POST /inference/yolo           — multipart, YOLO 문/창/가구 탐지
  - POST /internal/sionna/run      — JSON, Sionna RT 시뮬레이션

응답 contract:
  - JSON 본문에 핵심 메트릭/detection/values_dbm 등 들어옴
  - 큰 산출물 (.npy / .png) 은 별도 라우트 `/static/...` 으로 다운로드 (StaticFiles mount)
  - 모든 라우트가 sync long-poll (Sionna 는 분 단위, UNet/YOLO 는 초 단위)
  - 에러는 표준 envelope (`{detail: {error: {code, message, ...}}}`)

이 모듈은 기존 sagemaker_inference_service.InferenceResult / RfInferenceResult 와
호환되는 결과를 만들어서 fusion_service / rf_job_service 가 변경 없이 사용 가능하게 함.
"""
from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image

from app.core.errors import AppError, ErrorCode
from app.core.settings import ai_service_url
from app.services.sagemaker_inference_service import (
    InferenceResult,
    SageMakerInferenceFailure,
)
from app.services.sagemaker_rf_inference_service import (
    RfInferenceResult,
    SageMakerRfInferenceFailure,
)

logger = logging.getLogger(__name__)


# 라우트별 timeout (초). Sionna 가 가장 느림.
UNET_TIMEOUT_S = 120.0
YOLO_TIMEOUT_S = 60.0
SIONNA_TIMEOUT_S = 600.0
STATIC_TIMEOUT_S = 60.0

# wall mask 생성 threshold (UNet prob_map 이 [0,1] float → mask 는 binary)
WALL_PROB_THRESHOLD = 0.5


def _base_url() -> str:
    url = ai_service_url().rstrip("/")
    if not url:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AI_SERVICE_URL not configured.",
            503,
        )
    return url


def _raise_for_envelope(resp: httpx.Response, where: str) -> None:
    """ai_api 표준 envelope 에러 → AppError. 422 는 별도 처리."""
    if resp.status_code < 400:
        return
    try:
        body = resp.json()
    except Exception:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"ai_api {where} failed with HTTP {resp.status_code}: {resp.text[:200]}",
            502,
        )

    # FastAPI validation error (422)
    if resp.status_code == 422 and isinstance(body.get("detail"), list):
        raise AppError(
            ErrorCode.INVALID_REQUEST_BODY,
            f"ai_api {where} validation failed: {json.dumps(body['detail'])[:300]}",
            502,
        )

    # 표준 envelope
    detail = body.get("detail") or {}
    err = detail.get("error") or {}
    code = err.get("code") or "UNKNOWN"
    message = err.get("message") or f"ai_api {where} failed"
    raise AppError(
        ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
        f"ai_api {where} [{code}]: {message}",
        resp.status_code if resp.status_code in (400, 404, 415, 500, 502, 503) else 502,
    )


# ============================================================
# Static file fetch
# ============================================================
def fetch_static(relative_path: str) -> bytes:
    """ai_api 의 /static/... 에서 산출물 다운로드."""
    if not relative_path:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "ai_api static path is empty.",
            502,
        )
    # ai_api 가 절대경로를 그대로 줬을 가능성도 있음 — 로컬 디스크 경로면 못 받음.
    if relative_path.startswith("/static/"):
        url = _base_url() + relative_path
    elif relative_path.startswith("http://") or relative_path.startswith("https://"):
        url = relative_path
    elif relative_path.startswith("/"):
        # 절대경로가 그대로 옴 → ai_api StaticFiles mount 가 안 된 상태.
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"ai_api returned filesystem path (not /static/ URL): {relative_path}. "
            "Make sure ai_api has StaticFiles mounted.",
            502,
        )
    else:
        url = f"{_base_url()}/static/{relative_path.lstrip('/')}"

    with httpx.Client(timeout=STATIC_TIMEOUT_S) as client:
        resp = client.get(url)
    if resp.status_code >= 400:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"ai_api static fetch failed for {url}: HTTP {resp.status_code}",
            502,
        )
    return resp.content


# ============================================================
# Floorplan (UNet + YOLO) → InferenceResult
# ============================================================
async def analyze_floorplan(
    *,
    image_bytes: bytes,
    filename: str,
    file_id: str,
) -> InferenceResult:
    """ai_api UNet + YOLO 순차 호출 → 기존 InferenceResult 호환 형태로 반환.

    호출자가 result.cleanup() 책임 (기존 SageMaker 흐름과 동일).
    """
    import asyncio

    # ai_api 응답이 sync 라 둘을 await 로 직렬 호출. (ai_api 자체가 단일 worker 라
    # 동시 호출해봐야 직렬화돼서 의미 없음)
    unet_resp = await asyncio.to_thread(_post_unet, image_bytes, filename, file_id)
    yolo_resp = await asyncio.to_thread(_post_yolo, image_bytes, filename, file_id)

    # 결과 파일 fetch + temp 디렉토리 구성
    temp_dir = Path(tempfile.mkdtemp(prefix=f"aiapi-{file_id}-"))
    try:
        prob_map_path = temp_dir / "wall_prob_map.npy"
        mask_path = temp_dir / "wall_mask.png"
        source_path = temp_dir / f"source{Path(filename).suffix or '.png'}"

        prob_npy_path = unet_resp.get("output", {}).get("wallProbNpyPath")
        if not prob_npy_path:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "ai_api UNet response missing wallProbNpyPath.",
                502,
            )
        npy_bytes = await asyncio.to_thread(fetch_static, prob_npy_path)
        prob_map_path.write_bytes(npy_bytes)

        # mask PNG 생성 (기존 SageMaker 컨테이너는 별도 wall_mask.png 도 줬음 — ai_api 는
        # prob_map 만 주므로 binarize 해서 동일 인터페이스 채움)
        _binarize_npy_to_mask_png(prob_map_path, mask_path, WALL_PROB_THRESHOLD)

        # 원본 도면 이미지는 이미 메모리에 있으니 그대로 저장 (S3 다운로드 안 함)
        source_path.write_bytes(image_bytes)

        shape = unet_resp.get("metrics", {}).get("shape") or [0, 0]
        height_px, width_px = int(shape[0]), int(shape[1])

        detections = yolo_resp.get("output", {}).get("detections") or []

        return InferenceResult(
            job_id=file_id,
            temp_dir=temp_dir,
            prob_map_local_path=prob_map_path,
            mask_local_path=mask_path,
            detections=detections,
            image_width_px=width_px,
            image_height_px=height_px,
            result_payload={
                "unet": unet_resp,
                "yolo": yolo_resp,
                "image": {"width_px": width_px, "height_px": height_px},
            },
            source_image_local_path=source_path,
        )
    except Exception:
        # temp dir 청소 후 재예외
        try:
            for child in temp_dir.glob("*"):
                child.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            pass
        raise


def _post_unet(
    image_bytes: bytes, filename: str, file_id: str
) -> dict[str, Any]:
    url = f"{_base_url()}/inference/unet"
    files = {"file": (filename or "floorplan.png", image_bytes, "image/png")}
    data = {"file_id": file_id}
    with httpx.Client(timeout=UNET_TIMEOUT_S) as client:
        resp = client.post(url, files=files, data=data)
    _raise_for_envelope(resp, "UNet inference")
    return resp.json()


def _post_yolo(
    image_bytes: bytes, filename: str, file_id: str
) -> dict[str, Any]:
    url = f"{_base_url()}/inference/yolo"
    files = {"file": (filename or "floorplan.png", image_bytes, "image/png")}
    data = {"file_id": file_id}
    with httpx.Client(timeout=YOLO_TIMEOUT_S) as client:
        resp = client.post(url, files=files, data=data)
    _raise_for_envelope(resp, "YOLO inference")
    return resp.json()


def _binarize_npy_to_mask_png(
    npy_path: Path, png_path: Path, threshold: float
) -> None:
    arr = np.load(str(npy_path))
    mask = (arr >= threshold).astype(np.uint8) * 255
    img = Image.fromarray(mask, mode="L")
    img.save(str(png_path), format="PNG")


# ============================================================
# Sionna RT 시뮬레이션 → RfInferenceResult
# ============================================================
@dataclass
class _SionnaCallInputs:
    """Sionna 호출 입력 (scene + AP + plane + 옵션들). 호출자가 채워서 전달."""
    scene: dict[str, Any]
    access_point: dict[str, Any]
    measurement_plane: dict[str, Any]
    simulation: dict[str, Any] | None = None
    scene_defaults: dict[str, Any] | None = None
    antenna: dict[str, Any] | None = None
    visualization: dict[str, Any] | None = None
    materials: list[dict[str, Any]] | None = None
    correction_profile: dict[str, Any] | None = None
    run_type: str = "run"
    floor_id: str | None = None


async def simulate_rf(
    *,
    job_id: str,
    inputs: _SionnaCallInputs,
) -> tuple[RfInferenceResult, dict[str, Any]]:
    """ai_api POST /internal/sionna/run 호출. 동기 long-poll.

    반환:
      - RfInferenceResult (기존 SageMaker 호환 dataclass, storage_url 은 비어있음 — 호출자가 채움)
      - 원본 응답 dict (artifacts.radiomap.values_dbm 등 호출자가 PNG 만들 때 사용)
    """
    import asyncio

    payload: dict[str, Any] = {
        "engine": "sionna_rt",
        "run_type": inputs.run_type,
        "scene": inputs.scene,
        "access_point": inputs.access_point,
        "measurement_plane": inputs.measurement_plane,
    }
    if inputs.floor_id:
        payload["floor_id"] = inputs.floor_id
    if inputs.simulation is not None:
        payload["simulation"] = inputs.simulation
    if inputs.scene_defaults is not None:
        payload["scene_defaults"] = inputs.scene_defaults
    if inputs.antenna is not None:
        payload["antenna"] = inputs.antenna
    if inputs.visualization is not None:
        payload["visualization"] = inputs.visualization
    if inputs.materials is not None:
        payload["materials"] = inputs.materials
    if inputs.correction_profile is not None:
        payload["correction_profile"] = inputs.correction_profile

    url = f"{_base_url()}/internal/sionna/run"
    resp = await asyncio.to_thread(_post_sionna, url, payload)

    status = resp.get("status")
    if status != "succeeded":
        raise SageMakerRfInferenceFailure(
            code="SIMULATION_FAILED",
            stage="ai_api_sionna",
            message=f"ai_api Sionna returned status={status!r}",
            details={"response": resp},
            job_id=job_id,
        )

    artifacts = resp.get("artifacts") or {}
    return (
        RfInferenceResult(
            job_id=job_id,
            result_payload=resp,
            result_s3_uri="",          # ai_api 흐름엔 S3 URI 없음
            heatmap_s3_uri="",
            radio_map_s3_uri="",
        ),
        artifacts,
    )


def _post_sionna(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=SIONNA_TIMEOUT_S) as client:
        resp = client.post(url, json=payload)
    _raise_for_envelope(resp, "Sionna run")
    return resp.json()


# ============================================================
# Health check
# ============================================================
def ping_health() -> bool:
    """ai_api /health 200 OK 인지. 실패해도 raise 안 함."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{_base_url()}/health")
        return resp.status_code == 200
    except Exception:
        return False
