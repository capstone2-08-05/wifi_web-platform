"""백엔드 ↔ SageMaker Async Inference 컨테이너 클라이언트.

흐름:
  1. S3 에 source 이미지 업로드 (`projects/{project_id}/floors/{floor_id}/sources/{file_id}.{ext}`)
  2. input.json 생성 (계약 v1.0) + S3 업로드
  3. `invoke_endpoint_async` 호출
  4. output_prefix 의 result.json / failure.json 폴링
  5. 성공 시 raw outputs (wall_prob_map.npy, detections.json, ...) 를 로컬 temp 디렉토리로 다운로드
  6. `InferenceResult` 로 반환 — `fusion_service` 가 받아 변환 후 DB 저장

실패 케이스:
  - 컨테이너 측 application-level 실패 → output_prefix/failure.json → SageMakerInferenceFailure (code 보유)
  - SageMaker 인프라 실패 → S3FailurePath/{id}.out → INTERNAL_SERVER_ERROR 로 raise
  - 폴링 timeout → EXTERNAL_SERVICE_REQUEST_FAILED 로 raise

계약 문서: docs/contracts/ai-inference/
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    AWS_REGION,
    AWS_S3_BUCKET,
    SAGEMAKER_ENDPOINT_NAME,
    SAGEMAKER_POLL_INTERVAL_SECONDS,
    SAGEMAKER_POLL_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA_VERSION = "1.0"


# ============================================================
# 결과 / 실패 표현
# ============================================================
@dataclass
class InferenceResult:
    """SageMaker invocation 성공 결과를 fusion_service 에 전달하는 형태.

    raw outputs 는 로컬 temp 파일로 다운받아진 상태. 사용 후 temp_dir 를 cleanup 해야 함.
    """

    job_id: str
    temp_dir: Path
    prob_map_local_path: Path
    mask_local_path: Path
    detections: list[dict[str, Any]]   # detections.json 의 detections 배열
    image_width_px: int
    image_height_px: int
    result_payload: dict[str, Any]      # 원본 result.json (디버깅/메트릭)

    def cleanup(self) -> None:
        try:
            for child in self.temp_dir.glob("*"):
                child.unlink(missing_ok=True)
            self.temp_dir.rmdir()
        except OSError:
            logger.warning("temp dir cleanup failed: %s", self.temp_dir, exc_info=True)


@dataclass
class SageMakerInferenceFailure(Exception):
    """컨테이너가 명시적으로 쓴 failure.json 정보."""

    code: str            # ErrorCode (계약의 8종)
    stage: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None

    def __post_init__(self) -> None:  # dataclass + Exception 호환
        Exception.__init__(self, self.message)


# ============================================================
# 컨테이너 error.code → 백엔드 ErrorCode 매핑
# error_codes.md 의 "백엔드 매핑 (제안)" 표 기준
# ============================================================
_CONTAINER_TO_BACKEND_CODE: dict[str, ErrorCode] = {
    "INVALID_INPUT": ErrorCode.INTERNAL_SERVER_ERROR,             # 백엔드가 잘못된 input.json 만든 경우
    "UNSUPPORTED_SCHEMA_VERSION": ErrorCode.INTERNAL_SERVER_ERROR,
    "SOURCE_IMAGE_DOWNLOAD_FAILED": ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
    "SOURCE_IMAGE_DECODE_FAILED": ErrorCode.INVALID_FILE_EXTENSION,
    "UNET_INFERENCE_FAILED": ErrorCode.ANALYSIS_FAILED,
    "YOLO_INFERENCE_FAILED": ErrorCode.ANALYSIS_FAILED,
    "OUTPUT_UPLOAD_FAILED": ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
    "INTERNAL_ERROR": ErrorCode.INTERNAL_SERVER_ERROR,
}

_CONTAINER_TO_HTTP_STATUS: dict[str, int] = {
    "INVALID_INPUT": 500,
    "UNSUPPORTED_SCHEMA_VERSION": 500,
    "SOURCE_IMAGE_DOWNLOAD_FAILED": 502,
    "SOURCE_IMAGE_DECODE_FAILED": 400,
    "UNET_INFERENCE_FAILED": 502,
    "YOLO_INFERENCE_FAILED": 502,
    "OUTPUT_UPLOAD_FAILED": 502,
    "INTERNAL_ERROR": 500,
}


def map_failure_to_app_error(failure: SageMakerInferenceFailure) -> AppError:
    backend_code = _CONTAINER_TO_BACKEND_CODE.get(failure.code, ErrorCode.ANALYSIS_FAILED)
    http_status = _CONTAINER_TO_HTTP_STATUS.get(failure.code, 502)
    return AppError(
        backend_code,
        f"AI inference failed at stage '{failure.stage}': {failure.message}",
        http_status,
    )


# ============================================================
# Service
# ============================================================
class SageMakerInferenceService:
    """boto3 client 들을 lazy 생성하면서 의존성 주입 가능한 형태로."""

    def __init__(
        self,
        region: str = AWS_REGION,
        bucket: str = AWS_S3_BUCKET,
        endpoint_name: str = SAGEMAKER_ENDPOINT_NAME,
        poll_interval_seconds: float = SAGEMAKER_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = SAGEMAKER_POLL_TIMEOUT_SECONDS,
    ) -> None:
        self.region = region
        self.bucket = bucket
        self.endpoint_name = endpoint_name
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self._s3 = None
        self._smrt = None

    # ----- lazy clients -----
    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    def _get_smrt(self):
        if self._smrt is None:
            self._smrt = boto3.client("sagemaker-runtime", region_name=self.region)
        return self._smrt

    def _check_configured(self) -> None:
        if not self.bucket:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "AWS_S3_BUCKET not configured for SageMaker inference.",
                503,
            )
        if not self.endpoint_name:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "SAGEMAKER_ENDPOINT_NAME not configured.",
                503,
            )

    # ----- main entry -----
    async def invoke_and_wait(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        project_id: str,
        floor_id: str,
        content_type: str = "application/octet-stream",
    ) -> InferenceResult:
        """전체 흐름. blocking I/O 는 thread executor 로 우회."""
        self._check_configured()

        job_id = uuid.uuid4().hex
        ext = Path(filename).suffix.lower() or ".png"
        source_key = f"projects/{project_id}/floors/{floor_id}/sources/{job_id}{ext}"
        input_key = f"ai-jobs/{job_id}/input/input.json"
        output_prefix_uri = f"s3://{self.bucket}/ai-jobs/{job_id}/output/"
        input_s3_uri = f"s3://{self.bucket}/{input_key}"
        source_s3_uri = f"s3://{self.bucket}/{source_key}"

        logger.info("SageMaker job_id=%s source=%s", job_id, source_s3_uri)

        # blocking 부분을 default executor 에서
        return await asyncio.to_thread(
            self._run_pipeline_blocking,
            job_id=job_id,
            image_bytes=image_bytes,
            content_type=content_type,
            source_key=source_key,
            input_key=input_key,
            input_s3_uri=input_s3_uri,
            source_s3_uri=source_s3_uri,
            output_prefix_uri=output_prefix_uri,
            project_id=project_id,
            floor_id=floor_id,
        )

    def _run_pipeline_blocking(
        self,
        *,
        job_id: str,
        image_bytes: bytes,
        content_type: str,
        source_key: str,
        input_key: str,
        input_s3_uri: str,
        source_s3_uri: str,
        output_prefix_uri: str,
        project_id: str,
        floor_id: str,
    ) -> InferenceResult:
        s3 = self._get_s3()
        smrt = self._get_smrt()

        # 1) source 이미지 업로드
        try:
            s3.put_object(Bucket=self.bucket, Key=source_key, Body=image_bytes, ContentType=content_type)
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 source upload failed: {exc}",
                502,
            ) from exc

        # 2) input.json 업로드 (계약 v1.0)
        input_payload = {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "job_id": job_id,
            "project_id": project_id,
            "floor_id": floor_id,
            "source_image_s3_uri": source_s3_uri,
            "output_prefix": output_prefix_uri,
            "tasks": {"wall_segmentation": True, "object_detection": True},
        }
        try:
            s3.put_object(
                Bucket=self.bucket,
                Key=input_key,
                Body=json.dumps(input_payload).encode("utf-8"),
                ContentType="application/json",
            )
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 input.json upload failed: {exc}",
                502,
            ) from exc

        # 3) invoke_endpoint_async
        try:
            response = smrt.invoke_endpoint_async(
                EndpointName=self.endpoint_name,
                ContentType="application/json",
                InputLocation=input_s3_uri,
            )
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"SageMaker invoke_endpoint_async failed: {exc}",
                502,
            ) from exc

        inference_id = response.get("InferenceId", "")
        sagemaker_failure_location = response.get("FailureLocation", "")
        logger.info(
            "SageMaker async invoke OK job_id=%s inference_id=%s",
            job_id,
            inference_id,
        )

        # 4) result.json / failure.json 폴링
        result_key = f"ai-jobs/{job_id}/output/result.json"
        failure_key = f"ai-jobs/{job_id}/output/failure.json"

        deadline = time.time() + self.poll_timeout_seconds
        result_payload: dict[str, Any] | None = None
        while time.time() < deadline:
            if _s3_exists(s3, self.bucket, result_key):
                result_payload = json.loads(_s3_get_bytes(s3, self.bucket, result_key))
                break
            if _s3_exists(s3, self.bucket, failure_key):
                failure_payload = json.loads(_s3_get_bytes(s3, self.bucket, failure_key))
                raise self._parse_failure(failure_payload, job_id)
            # SageMaker 인프라 실패도 함께 확인 — FailureLocation 에 SageMaker 가 직접 쓰는 객체
            if sagemaker_failure_location and _s3_uri_exists(s3, sagemaker_failure_location):
                logger.error(
                    "SageMaker FailureLocation populated job_id=%s loc=%s",
                    job_id,
                    sagemaker_failure_location,
                )
                raise AppError(
                    ErrorCode.INTERNAL_SERVER_ERROR,
                    f"SageMaker infrastructure error (see {sagemaker_failure_location})",
                    502,
                )
            time.sleep(self.poll_interval_seconds)

        if result_payload is None:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"SageMaker inference timed out after {self.poll_timeout_seconds}s (job_id={job_id})",
                504,
            )

        # 5) raw outputs 다운로드 (필요한 것만)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"sm-{job_id}-"))
        prob_map_path = temp_dir / "wall_prob_map.npy"
        mask_path = temp_dir / "wall_mask.png"
        try:
            _s3_download(s3, self.bucket, f"ai-jobs/{job_id}/output/wall_prob_map.npy", prob_map_path)
            _s3_download(s3, self.bucket, f"ai-jobs/{job_id}/output/wall_mask.png", mask_path)
            detections_bytes = _s3_get_bytes(
                s3, self.bucket, f"ai-jobs/{job_id}/output/detections.json"
            )
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 download of raw outputs failed: {exc}",
                502,
            ) from exc

        detections_payload = json.loads(detections_bytes)
        detections = list(detections_payload.get("detections") or [])

        image_info = result_payload.get("image", {})
        return InferenceResult(
            job_id=job_id,
            temp_dir=temp_dir,
            prob_map_local_path=prob_map_path,
            mask_local_path=mask_path,
            detections=detections,
            image_width_px=int(image_info.get("width_px", 0)),
            image_height_px=int(image_info.get("height_px", 0)),
            result_payload=result_payload,
        )

    @staticmethod
    def _parse_failure(payload: dict[str, Any], job_id: str) -> SageMakerInferenceFailure:
        error = payload.get("error") or {}
        return SageMakerInferenceFailure(
            code=str(error.get("code") or "INTERNAL_ERROR"),
            stage=str(error.get("stage") or "unknown"),
            message=str(error.get("message") or "AI inference failed"),
            retryable=bool(error.get("retryable", False)),
            details=dict(error.get("details") or {}),
            job_id=str(payload.get("job_id") or job_id),
        )


# ============================================================
# S3 helpers (단일 client 받아서 동작)
# ============================================================
def _s3_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _s3_uri_exists(s3, uri: str) -> bool:
    if not uri.startswith("s3://"):
        return False
    _, _, rest = uri.partition("s3://")
    bucket, _, key = rest.partition("/")
    if not key:
        return False
    return _s3_exists(s3, bucket, key)


def _s3_get_bytes(s3, bucket: str, key: str) -> bytes:
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _s3_download(s3, bucket: str, key: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, str(dest))


sagemaker_inference_service = SageMakerInferenceService()
