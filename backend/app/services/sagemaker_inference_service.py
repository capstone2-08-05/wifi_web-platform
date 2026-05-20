"""백엔드 ↔ SageMaker Async Inference 컨테이너 클라이언트.

Job 비동기 패턴용 4-단계 API:
  1. `submit(...)` — S3 source/input.json 업로드 + invoke_endpoint_async + SubmitResult 반환 (블록 X)
  2. `check_status(output_prefix)` — S3 head_object 로 result/failure 존재 확인 → "running"/"completed"/"failed"
  3. `download_result(job_id, output_prefix)` — result.json + raw outputs (npy/png/detections) 다운로드
  4. `download_failure(output_prefix)` — failure.json 파싱

기존 `invoke_and_wait(...)` 는 호출자가 폴링을 의식하지 않아도 되지만, HTTP 요청을 5-15분 블록함.
새 API 는 폴링 책임을 호출자(`floorplan_job_service`)에게 위임.

실패 케이스:
  - 컨테이너 측 application-level 실패 → output_prefix/failure.json → SageMakerInferenceFailure (code 보유)
  - SageMaker 인프라 실패 → S3FailurePath/{id}.out → INTERNAL_SERVER_ERROR 로 raise
  - 폴링 timeout 은 호출자 정책 (Job.created_at 으로부터 N 분 경과 시 cleanup 등)

계약 문서: docs/contracts/ai-inference/
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError

from app.core.aws import BOTO_CONFIG
from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    AWS_REGION,
    AWS_S3_BUCKET,
    SAGEMAKER_ENDPOINT_NAME,
)

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA_VERSION = "1.0"

InferenceStatus = Literal["running", "completed", "failed", "infra_failed"]


# ============================================================
# 결과 / 실패 표현
# ============================================================
@dataclass
class SubmitResult:
    """SageMaker invoke_endpoint_async 직후 반환.

    Job row 의 input_json 에 그대로 직렬화해 저장. 폴링 단계에서 output_prefix 기반으로
    결과 확인.
    """

    job_id: str
    sagemaker_inference_id: str
    source_s3_uri: str
    input_s3_uri: str
    output_prefix: str
    sagemaker_output_location: str
    sagemaker_failure_location: str


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
    # 원본 도면 이미지 (S3 에서 다운). OCR/선분 검출에 필요. 다운로드 실패 시 None.
    source_image_local_path: Path | None = None
    # 사전 분석 priors — AI 서버가 같이 내려주면 채워짐. 없으면 None → 백엔드가 자체 fallback.
    # 형식은 packages/contracts/inference.py 의 OcrPrior/LinePrior/RoiTransform 와 일치.
    ocr_priors: list[dict[str, Any]] | None = None    # [{text, bbox:[x1,y1,x2,y2], confidence}]
    line_priors: list[dict[str, Any]] | None = None   # [{x1,y1,x2,y2,angle_deg?,length_px?}]
    roi_transform: dict[str, Any] | None = None       # {offset_x, offset_y, width, height}

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
    ) -> None:
        self.region = region
        self.bucket = bucket
        self.endpoint_name = endpoint_name
        self._s3 = None
        self._smrt = None

    # ----- lazy clients (bounded timeout — hang 방지) -----
    def _get_s3(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self.region, config=BOTO_CONFIG)
        return self._s3

    def _get_smrt(self):
        if self._smrt is None:
            self._smrt = boto3.client(
                "sagemaker-runtime", region_name=self.region, config=BOTO_CONFIG
            )
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

    # ----- 1. submit -----
    async def submit(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        project_id: str,
        floor_id: str,
        content_type: str = "application/octet-stream",
    ) -> SubmitResult:
        """source/input.json S3 업로드 + invoke_endpoint_async. **블록 안 함**.

        blocking I/O (boto3) 는 thread executor 로 우회.
        """
        self._check_configured()

        job_id = uuid.uuid4().hex
        ext = Path(filename).suffix.lower() or ".png"
        source_key = f"projects/{project_id}/floors/{floor_id}/sources/{job_id}{ext}"
        input_key = f"ai-jobs/{job_id}/input/input.json"
        output_prefix_uri = f"s3://{self.bucket}/ai-jobs/{job_id}/output/"
        input_s3_uri = f"s3://{self.bucket}/{input_key}"
        source_s3_uri = f"s3://{self.bucket}/{source_key}"

        logger.info("SageMaker submit start job_id=%s source=%s", job_id, source_s3_uri)

        return await asyncio.to_thread(
            self._submit_blocking,
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

    def _submit_blocking(
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
    ) -> SubmitResult:
        s3 = self._get_s3()
        smrt = self._get_smrt()

        # 1) source 이미지 업로드
        try:
            s3.put_object(
                Bucket=self.bucket, Key=source_key, Body=image_bytes, ContentType=content_type
            )
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 source upload failed: {exc}",
                502,
            ) from exc

        # 2) input.json 업로드
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
        sagemaker_output_location = response.get("OutputLocation", "")
        sagemaker_failure_location = response.get("FailureLocation", "")
        logger.info(
            "SageMaker submit OK job_id=%s inference_id=%s",
            job_id,
            inference_id,
        )

        return SubmitResult(
            job_id=job_id,
            sagemaker_inference_id=inference_id,
            source_s3_uri=source_s3_uri,
            input_s3_uri=input_s3_uri,
            output_prefix=output_prefix_uri,
            sagemaker_output_location=sagemaker_output_location,
            sagemaker_failure_location=sagemaker_failure_location,
        )

    # ----- 2. check_status -----
    def check_status(
        self,
        output_prefix: str,
        sagemaker_failure_location: str = "",
    ) -> InferenceStatus:
        """S3 head_object 로 결과 존재 확인 (cheap call).

        - result.json 보이면 → "completed"
        - failure.json 보이면 → "failed" (컨테이너 측 application-level 실패)
        - SageMaker FailureLocation 보이면 → "infra_failed" (인프라 실패)
        - 둘 다 없으면 → "running"
        """
        bucket, prefix_key = _split_s3_uri(output_prefix)
        s3 = self._get_s3()

        if _s3_exists(s3, bucket, prefix_key + "result.json"):
            return "completed"
        if _s3_exists(s3, bucket, prefix_key + "failure.json"):
            return "failed"
        if sagemaker_failure_location and _s3_uri_exists(s3, sagemaker_failure_location):
            return "infra_failed"
        return "running"

    # ----- 3. download_result -----
    def download_result(
        self,
        job_id: str,
        output_prefix: str,
        source_s3_uri: str | None = None,
    ) -> InferenceResult:
        """result.json + raw outputs 를 temp 디렉토리로 다운로드.

        source_s3_uri 가 주어지면 원본 도면 이미지도 같이 다운 (OCR/선분 검출용).
        호출 후 반드시 InferenceResult.cleanup() 으로 정리할 것.
        """
        bucket, prefix_key = _split_s3_uri(output_prefix)
        s3 = self._get_s3()

        try:
            result_payload = json.loads(_s3_get_bytes(s3, bucket, prefix_key + "result.json"))
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 result.json read failed: {exc}",
                502,
            ) from exc

        temp_dir = Path(tempfile.mkdtemp(prefix=f"sm-{job_id}-"))
        prob_map_path = temp_dir / "wall_prob_map.npy"
        mask_path = temp_dir / "wall_mask.png"
        try:
            _s3_download(s3, bucket, prefix_key + "wall_prob_map.npy", prob_map_path)
            _s3_download(s3, bucket, prefix_key + "wall_mask.png", mask_path)
            detections_bytes = _s3_get_bytes(s3, bucket, prefix_key + "detections.json")
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 download of raw outputs failed: {exc}",
                502,
            ) from exc

        # 원본 이미지 다운 (best-effort — 실패해도 인퍼런스 결과 자체는 살림).
        source_image_path: Path | None = None
        if source_s3_uri:
            try:
                src_bucket, src_key = _split_s3_uri(source_s3_uri)
                ext = Path(src_key).suffix or ".png"
                source_image_path = temp_dir / f"source{ext}"
                _s3_download(s3, src_bucket, src_key, source_image_path)
            except (ClientError, ValueError) as exc:
                logger.warning(
                    "source image download failed (OCR/line detection 비활성화됨): %s", exc
                )
                source_image_path = None

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
            source_image_local_path=source_image_path,
        )

    # ----- 4. download_failure -----
    def download_failure(self, output_prefix: str) -> SageMakerInferenceFailure:
        """failure.json 파싱."""
        bucket, prefix_key = _split_s3_uri(output_prefix)
        s3 = self._get_s3()
        failure_payload = json.loads(_s3_get_bytes(s3, bucket, prefix_key + "failure.json"))
        return self._parse_failure(failure_payload, str(failure_payload.get("job_id") or ""))

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
# S3 helpers
# ============================================================
def _split_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/key/path/ → (bucket, 'key/path/')."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri!r}")
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


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
    bucket, key = _split_s3_uri(uri)
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
