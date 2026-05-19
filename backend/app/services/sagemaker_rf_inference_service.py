"""[DEPRECATED] 백엔드 ↔ SageMaker Async RF Inference 컨테이너 클라이언트.

⚠️ AWS 회귀 시 복원: 이 모듈의 클래스 메서드들은 모두 비활성화됐다.
   현재 RF 시뮬 흐름은 app/services/ai_inference_client.simulate_rf 가 사용한다.

복원 절차:
  1. SageMakerRfInferenceService 의 각 메서드에서 raise 줄 제거
  2. boto3 / botocore import 복원
  3. rf_job_service.submit_rf_simulation 의 ai_inference_client 호출을 sagemaker
     호출로 교체 (_run_rf_pipeline_in_background → 옛 _complete_rf_job 흐름)
  4. AWS_REGION / AWS_S3_BUCKET / SAGEMAKER_RF_ENDPOINT_NAME env 재설정

dataclass (RfSubmitResult, RfInferenceResult, SageMakerRfInferenceFailure) 는 보존.
ai_inference_client 가 SageMakerRfInferenceFailure 를 재사용한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

# boto3 / botocore 는 lazy import (AWS 회귀 시 모듈 레벨로 복원)
from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    AWS_REGION,
    AWS_S3_BUCKET,
    RF_PRESIGNED_URL_EXPIRES_SECONDS,
    SAGEMAKER_RF_ENDPOINT_NAME,
)

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA_VERSION = "1.0"

RfInferenceStatus = Literal["running", "completed", "failed", "infra_failed"]


# ============================================================
# 결과 / 실패 표현
# ============================================================
@dataclass
class RfSubmitResult:
    """SageMaker invoke_endpoint_async 직후 반환. Job.input_json 으로 영속화 가능."""

    job_id: str
    sagemaker_inference_id: str
    scene_s3_uri: str
    input_s3_uri: str
    output_prefix: str
    sagemaker_output_location: str
    sagemaker_failure_location: str


@dataclass
class RfInferenceResult:
    """RF 시뮬 성공 결과. raw 파일은 다운받지 않고 URI 만 보관."""

    job_id: str
    result_payload: dict[str, Any]   # 원본 result.json
    result_s3_uri: str
    heatmap_s3_uri: str
    radio_map_s3_uri: str


@dataclass
class SageMakerRfInferenceFailure(Exception):
    """컨테이너가 명시적으로 쓴 failure.json 정보."""

    code: str            # ErrorCode (계약의 7종)
    stage: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


# ============================================================
# 컨테이너 error.code → 백엔드 ErrorCode 매핑
# docs/contracts/rf-inference/error_codes.md 기준
# ============================================================
_CONTAINER_TO_BACKEND_CODE: dict[str, ErrorCode] = {
    "INVALID_INPUT": ErrorCode.INTERNAL_SERVER_ERROR,
    "UNSUPPORTED_SCHEMA_VERSION": ErrorCode.INTERNAL_SERVER_ERROR,
    "SCENE_DOWNLOAD_FAILED": ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
    "SCENE_PARSE_FAILED": ErrorCode.INTERNAL_SERVER_ERROR,
    "SIMULATION_FAILED": ErrorCode.RF_SIMULATION_FAILED,
    "OUTPUT_UPLOAD_FAILED": ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
    "INTERNAL_ERROR": ErrorCode.INTERNAL_SERVER_ERROR,
}

_CONTAINER_TO_HTTP_STATUS: dict[str, int] = {
    "INVALID_INPUT": 500,
    "UNSUPPORTED_SCHEMA_VERSION": 500,
    "SCENE_DOWNLOAD_FAILED": 502,
    "SCENE_PARSE_FAILED": 500,
    "SIMULATION_FAILED": 502,
    "OUTPUT_UPLOAD_FAILED": 502,
    "INTERNAL_ERROR": 500,
}


def map_rf_failure_to_app_error(failure: SageMakerRfInferenceFailure) -> AppError:
    backend_code = _CONTAINER_TO_BACKEND_CODE.get(
        failure.code, ErrorCode.RF_SIMULATION_FAILED
    )
    http_status = _CONTAINER_TO_HTTP_STATUS.get(failure.code, 502)
    return AppError(
        backend_code,
        f"RF simulation failed at stage '{failure.stage}': {failure.message}",
        http_status,
    )


# ============================================================
# Service
# ============================================================
class SageMakerRfInferenceService:
    """boto3 client 들을 lazy 생성하면서 의존성 주입 가능한 형태로."""

    def __init__(
        self,
        region: str = AWS_REGION,
        bucket: str = AWS_S3_BUCKET,
        endpoint_name: str = SAGEMAKER_RF_ENDPOINT_NAME,
    ) -> None:
        self.region = region
        self.bucket = bucket
        self.endpoint_name = endpoint_name
        self._s3 = None
        self._smrt = None

    # ----- lazy clients (DEPRECATED: AWS 회귀 시 boto3 import 를 모듈 레벨로) -----
    def _get_s3(self):
        if self._s3 is None:
            import boto3
            from app.core.aws import BOTO_CONFIG
            self._s3 = boto3.client("s3", region_name=self.region, config=BOTO_CONFIG)
        return self._s3

    def _get_smrt(self):
        if self._smrt is None:
            import boto3
            from app.core.aws import BOTO_CONFIG
            self._smrt = boto3.client(
                "sagemaker-runtime", region_name=self.region, config=BOTO_CONFIG
            )
        return self._smrt

    def _check_configured(self) -> None:
        if not self.bucket:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "AWS_S3_BUCKET not configured for RF inference.",
                503,
            )
        if not self.endpoint_name:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                "SAGEMAKER_RF_ENDPOINT_NAME not configured.",
                503,
            )

    # ----- 1. submit -----
    async def submit(
        self,
        *,
        scene_json: dict[str, Any],
        project_id: str,
        floor_id: str,
        scene_version_id: str,
        simulation: dict[str, Any],
        access_points: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> RfSubmitResult:
        """[DEPRECATED] AWS 회귀 시 raise 줄 제거. ai_inference_client.simulate_rf 가 대체."""
        raise NotImplementedError("SageMaker RF path disabled.")
        self._check_configured()  # type: ignore[unreachable]

        job_id = uuid.uuid4().hex
        scene_key = f"rf-jobs/{job_id}/input/scene.json"
        input_key = f"rf-jobs/{job_id}/input/input.json"
        scene_s3_uri = f"s3://{self.bucket}/{scene_key}"
        input_s3_uri = f"s3://{self.bucket}/{input_key}"
        output_prefix_uri = f"s3://{self.bucket}/rf-jobs/{job_id}/output/"

        logger.info(
            "RF SageMaker submit start job_id=%s scene_version_id=%s num_aps=%d",
            job_id, scene_version_id, len(access_points),
        )

        input_payload: dict[str, Any] = {
            "schema_version": CONTRACT_SCHEMA_VERSION,
            "job_id": job_id,
            "project_id": project_id,
            "floor_id": floor_id,
            "scene_version_id": scene_version_id,
            "scene_s3_uri": scene_s3_uri,
            "output_prefix": output_prefix_uri,
            "simulation": simulation,
            "access_points": access_points,
        }
        if metadata:
            input_payload["metadata"] = metadata

        return await asyncio.to_thread(
            self._submit_blocking,
            job_id=job_id,
            scene_json=scene_json,
            input_payload=input_payload,
            scene_key=scene_key,
            input_key=input_key,
            scene_s3_uri=scene_s3_uri,
            input_s3_uri=input_s3_uri,
            output_prefix_uri=output_prefix_uri,
        )

    def _submit_blocking(
        self,
        *,
        job_id: str,
        scene_json: dict[str, Any],
        input_payload: dict[str, Any],
        scene_key: str,
        input_key: str,
        scene_s3_uri: str,
        input_s3_uri: str,
        output_prefix_uri: str,
    ) -> RfSubmitResult:
        s3 = self._get_s3()
        smrt = self._get_smrt()

        # 1) scene.json 업로드
        try:
            s3.put_object(
                Bucket=self.bucket,
                Key=scene_key,
                Body=json.dumps(scene_json).encode("utf-8"),
                ContentType="application/json",
            )
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 scene.json upload failed: {exc}",
                502,
            ) from exc

        # 2) input.json 업로드
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
                f"SageMaker invoke_endpoint_async (RF) failed: {exc}",
                502,
            ) from exc

        inference_id = response.get("InferenceId", "")
        sagemaker_output_location = response.get("OutputLocation", "")
        sagemaker_failure_location = response.get("FailureLocation", "")
        logger.info(
            "RF SageMaker submit OK job_id=%s inference_id=%s",
            job_id, inference_id,
        )

        return RfSubmitResult(
            job_id=job_id,
            sagemaker_inference_id=inference_id,
            scene_s3_uri=scene_s3_uri,
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
    ) -> RfInferenceStatus:
        """[DEPRECATED]"""
        raise NotImplementedError("SageMaker RF path disabled.")
        """S3 head_object 로 결과 존재 확인 (cheap call).

        - result.json 보이면 → "completed"
        - failure.json 보이면 → "failed"
        - SageMaker FailureLocation 보이면 → "infra_failed"
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
    def download_result(self, job_id: str, output_prefix: str) -> RfInferenceResult:
        """[DEPRECATED] AWS 회귀 시 raise 줄 제거."""
        raise NotImplementedError("SageMaker RF path disabled.")
        bucket, prefix_key = _split_s3_uri(output_prefix)  # type: ignore[unreachable]
        s3 = self._get_s3()

        try:
            result_payload = json.loads(_s3_get_bytes(s3, bucket, prefix_key + "result.json"))
        except ClientError as exc:
            raise AppError(
                ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
                f"S3 result.json read failed: {exc}",
                502,
            ) from exc

        outputs = result_payload.get("outputs") or {}
        return RfInferenceResult(
            job_id=job_id,
            result_payload=result_payload,
            result_s3_uri=str(outputs.get("result_s3_uri") or ""),
            heatmap_s3_uri=str(outputs.get("heatmap_s3_uri") or ""),
            radio_map_s3_uri=str(outputs.get("radio_map_s3_uri") or ""),
        )

    # ----- 4. download_failure -----
    def download_failure(self, output_prefix: str) -> SageMakerRfInferenceFailure:
        """[DEPRECATED]"""
        raise NotImplementedError("SageMaker RF path disabled.")
        bucket, prefix_key = _split_s3_uri(output_prefix)  # type: ignore[unreachable]
        s3 = self._get_s3()
        failure_payload = json.loads(_s3_get_bytes(s3, bucket, prefix_key + "failure.json"))
        return self._parse_failure(failure_payload, str(failure_payload.get("job_id") or ""))

    @staticmethod
    def _parse_failure(payload: dict[str, Any], job_id: str) -> SageMakerRfInferenceFailure:
        error = payload.get("error") or {}
        return SageMakerRfInferenceFailure(
            code=str(error.get("code") or "INTERNAL_ERROR"),
            stage=str(error.get("stage") or "unknown"),
            message=str(error.get("message") or "RF inference failed"),
            retryable=bool(error.get("retryable", False)),
            details=dict(error.get("details") or {}),
            job_id=str(payload.get("job_id") or job_id),
        )

    # ----- 5. presigned URL -----
    def presigned_url(
        self, s3_uri: str, expires_seconds: int = RF_PRESIGNED_URL_EXPIRES_SECONDS
    ) -> str:
        """[DEPRECATED] 로컬 흐름에선 _local_storage.static_url 사용."""
        raise NotImplementedError("SageMaker RF presigned URL disabled. Use _local_storage.static_url.")
        if not s3_uri:  # type: ignore[unreachable]
            return ""
        bucket, key = _split_s3_uri(s3_uri)
        s3 = self._get_s3()
        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=int(expires_seconds),
        )


# ============================================================
# S3 helpers (sagemaker_inference_service 와 동일 — 시뮬용으로 가벼움)
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


sagemaker_rf_inference_service = SageMakerRfInferenceService()
