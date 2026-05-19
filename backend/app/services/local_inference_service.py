"""로컬 AI 서버 (`AI_SERVICE_URL`) 기반 동기 추론 클라이언트.

SageMaker async 흐름과 동일한 `InferenceResult` dataclass 를 만들어 fusion_service
에 넘기는 것이 목적. 로컬 모드 토글이 켜진 분석 호출이 들어오면
`floorplan_job_service._run_local_in_background` 가 이 모듈을 호출.

AI 서버 계약 (rf-service/packages/contracts/inference.py):
  - `POST {AI_SERVICE_URL}/inference/unet` (multipart `file` + form `file_id`)
    응답: `{ status, task, fileId, output: { wallProbNpyPath, wallProbOverlayPath },
            metrics: { shape, dtype, minProb, maxProb, ... } }`
  - `POST {AI_SERVICE_URL}/inference/yolo` (multipart `file` + form `file_id`)
    응답: `{ status, task, fileId,
            output: { detections: [{class_id, class_name, confidence, bbox}], previewPath },
            metrics: { detectionCount, ... } }`

`*Path` 필드들은 AI 서버 로컬 FS 경로 (같은 머신이라 백엔드가 직접 np.load/read_bytes).
HTTP 환경으로 분리되면 `_load_npy_from_path_or_url` 가 URL fallback 도 처리.
"""
from __future__ import annotations

import io
import logging
import mimetypes
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

from app.core.errors import AppError, ErrorCode
from app.services.sagemaker_inference_service import InferenceResult

logger = logging.getLogger(__name__)


def run_local_inference(
    *,
    image_bytes: bytes,
    filename: str,
    content_type: str,
    ai_service_url: str,
    request_timeout_s: float = 120.0,
) -> InferenceResult:
    """이미지 바이트 → 로컬 AI 두 endpoint 호출 → SageMaker 와 같은 `InferenceResult`.

    호출자가 결과의 `temp_dir` cleanup 책임.
    """
    if not ai_service_url:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AI_SERVICE_URL not configured for local inference.",
            503,
        )

    base = ai_service_url.rstrip("/")
    job_id = uuid.uuid4().hex
    temp_dir = Path(tempfile.mkdtemp(prefix=f"local-{job_id}-"))
    logger.info("local inference start job_id=%s base=%s filename=%s", job_id, base, filename)

    try:
        # 1) source 이미지 — temp 보관 (OCR/선분 검출 입력용)
        suffix = Path(filename).suffix.lower() or ".png"
        source_image_path = temp_dir / f"source{suffix}"
        source_image_path.write_bytes(image_bytes)

        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # 2) unet 호출
        logger.info("local inference: POST /inference/unet job_id=%s", job_id)
        unet_payload = _post_inference(
            f"{base}/inference/unet",
            file_id=job_id,
            filename=filename,
            image_bytes=image_bytes,
            content_type=ctype,
            timeout=request_timeout_s,
        )
        unet_out = _require_output(unet_payload, task="unet")
        unet_metrics = unet_payload.get("metrics") or {}
        logger.info(
            "local inference: unet ok job_id=%s shape=%s",
            job_id, unet_metrics.get("shape"),
        )

        # 3) prob_map 로드 (계약: output.wallProbNpyPath)
        prob_map = _load_npy_from_path_or_url(
            _require_str(unet_out, "wallProbNpyPath"),
            base_url=base,
            timeout=request_timeout_s,
        )
        prob_map = _validate_prob_map_shape(prob_map)
        prob_map_path = temp_dir / "wall_prob_map.npy"
        np.save(str(prob_map_path), prob_map)

        # 4) overlay PNG 저장 (계약: output.wallProbOverlayPath, optional FS copy)
        mask_local_path = temp_dir / "wall_mask.png"
        _copy_overlay_or_fallback(
            unet_out.get("wallProbOverlayPath"), mask_local_path, prob_map,
        )

        # 5) yolo 호출 (detections 는 inline list — 계약: output.detections[])
        logger.info("local inference: POST /inference/yolo job_id=%s", job_id)
        yolo_payload = _post_inference(
            f"{base}/inference/yolo",
            file_id=job_id,
            filename=filename,
            image_bytes=image_bytes,
            content_type=ctype,
            timeout=request_timeout_s,
        )
        yolo_out = _require_output(yolo_payload, task="yolo")
        detections_raw = yolo_out.get("detections")
        if not isinstance(detections_raw, list):
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"yolo response output.detections is not a list (got {type(detections_raw).__name__})",
                502,
            )
        # 계약: {class_id, class_name, confidence, bbox: [x1,y1,x2,y2]}
        # fusion_service._build_ml_output_from_inference 가 동일 키들을 읽음.
        detections = list(detections_raw)
        logger.info(
            "local inference: yolo ok job_id=%s detections=%d",
            job_id, len(detections),
        )

        # 6) 이미지 dims — unet metrics.shape = [H, W] 우선, 없으면 prob_map shape.
        width_px, height_px = _extract_image_dims(unet_metrics, prob_map)

        # fusion_service._build_sagemaker_meta 가 읽는 최소 필드만 채움.
        now_iso = datetime.now(timezone.utc).isoformat()
        result_payload: dict[str, Any] = {
            "inference_id": f"local-{job_id}",
            "endpoint_name": "local-inference",
            "started_at": now_iso,
            "completed_at": now_iso,
            "image": {"width_px": width_px, "height_px": height_px},
        }

        return InferenceResult(
            job_id=job_id,
            temp_dir=temp_dir,
            prob_map_local_path=prob_map_path,
            mask_local_path=mask_local_path,
            detections=detections,
            image_width_px=width_px,
            image_height_px=height_px,
            result_payload=result_payload,
            source_image_local_path=source_image_path,
        )
    except Exception:
        # 실패하면 temp 정리하고 예외 다시 던짐 — 성공시엔 호출자 책임.
        for child in temp_dir.glob("*"):
            try:
                child.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass
        raise


# ───────────────────────────────────────────────────────────────────────────
# HTTP 호출
# ───────────────────────────────────────────────────────────────────────────
def _post_inference(
    url: str,
    *,
    file_id: str,
    filename: str,
    image_bytes: bytes,
    content_type: str,
    timeout: float,
) -> dict[str, Any]:
    """AI 서버 multipart 호출. `file_id` form field + `file` 파일 (계약)."""
    try:
        resp = requests.post(
            url,
            data={"file_id": file_id},
            files={"file": (filename, io.BytesIO(image_bytes), content_type)},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"Local AI request failed ({url}): {exc}",
            502,
        ) from exc

    if resp.status_code >= 400:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"Local AI {url} returned HTTP {resp.status_code}: {resp.text[:300]}",
            502,
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"Local AI {url} returned non-JSON body: {resp.text[:300]}",
            502,
        ) from exc


# ───────────────────────────────────────────────────────────────────────────
# 계약 검증 헬퍼
# ───────────────────────────────────────────────────────────────────────────
def _require_output(payload: dict[str, Any], *, task: str) -> dict[str, Any]:
    """`{status, task, output: {...}}` 형태에서 `output` dict 강제."""
    if not isinstance(payload, dict):
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"{task} response is not a JSON object",
            502,
        )
    output = payload.get("output")
    if not isinstance(output, dict):
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"{task} response missing 'output' object. Got fields: {sorted(payload.keys())}",
            502,
        )
    return output


def _require_str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"Local AI output missing required field '{key}' (got {type(v).__name__}). "
            f"Available: {sorted(d.keys())}",
            502,
        )
    return v


# ───────────────────────────────────────────────────────────────────────────
# 파일 로더 (로컬 FS 우선, URL fallback)
# ───────────────────────────────────────────────────────────────────────────
def _load_npy_from_path_or_url(value: str, *, base_url: str, timeout: float) -> np.ndarray:
    """AI 서버가 돌려준 경로/URL 에서 .npy 로드.

    1) `http(s)://...` → HTTP GET
    2) 로컬 FS 경로로 파일 존재 → `np.load` 직접
    3) `/...` 절대 경로지만 FS 에 없으면 `base_url + path` 로 GET
    """
    if value.startswith(("http://", "https://")):
        logger.info("npy source: URL %s", value)
        r = requests.get(value, timeout=timeout)
        r.raise_for_status()
        return np.load(io.BytesIO(r.content), allow_pickle=False)

    p = Path(value)
    if p.exists() and p.is_file():
        logger.info("npy source: local FS %s", value)
        return np.load(str(p), allow_pickle=False)

    if value.startswith("/"):
        url = base_url.rstrip("/") + value
        logger.info("npy source: server-relative URL %s", url)
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return np.load(io.BytesIO(r.content), allow_pickle=False)

    raise AppError(
        ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
        f"Cannot resolve npy path/url: {value}",
        502,
    )


def _copy_overlay_or_fallback(
    overlay_path: Any, dest: Path, prob_map: np.ndarray,
) -> None:
    """AI 서버의 overlay PNG 를 mask 자리에 복사. 실패하면 prob_map>0.5 로 2진화."""
    if isinstance(overlay_path, str) and overlay_path:
        try:
            p = Path(overlay_path)
            if p.exists() and p.is_file():
                dest.write_bytes(p.read_bytes())
                return
            logger.warning("overlay path 존재하지 않음 (%s) → prob_map fallback", overlay_path)
        except Exception as exc:
            logger.warning("overlay path copy 실패: %s → prob_map fallback", exc)

    # prob_map>0.5 이진화
    try:
        import cv2
        mask = (prob_map > 0.5).astype(np.uint8) * 255
        cv2.imwrite(str(dest), mask)
    except Exception as exc:
        logger.warning("wall_mask 생성 실패 (무시): %s", exc)


def _extract_image_dims(
    unet_metrics: dict[str, Any], prob_map: np.ndarray
) -> tuple[int, int]:
    """unet metrics.shape = [H, W] (계약) 우선, 없으면 prob_map shape (H, W)."""
    shape = unet_metrics.get("shape")
    if isinstance(shape, list) and len(shape) >= 2:
        try:
            h, w = int(shape[0]), int(shape[1])
            if h > 0 and w > 0:
                return w, h
        except (TypeError, ValueError):
            pass
    return int(prob_map.shape[1]), int(prob_map.shape[0])


def _validate_prob_map_shape(arr: np.ndarray) -> np.ndarray:
    if arr.ndim != 2:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"prob_map 은 2D 가 필요. got shape={arr.shape}",
            502,
        )
    return arr.astype(np.float32, copy=False)
