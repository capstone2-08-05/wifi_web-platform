"""sagemaker_inference_service 단위 테스트.

boto3 호출은 mock 으로 우회. failure.json 파싱 + error 매핑에 집중.
"""
from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.services.sagemaker_inference_service import (
    SageMakerInferenceFailure,
    SageMakerInferenceService,
    map_failure_to_app_error,
)


def test_parse_failure_unet_inference_failed():
    payload = {
        "schema_version": "1.0",
        "status": "failed",
        "job_id": "job-1",
        "failed_at": "2026-05-13T03:00:00Z",
        "error": {
            "code": "UNET_INFERENCE_FAILED",
            "stage": "wall_segmentation",
            "message": "CUDA OOM",
            "retryable": True,
            "details": {"image_size": [1600, 1200]},
        },
    }
    failure = SageMakerInferenceService._parse_failure(payload, "job-1")
    assert failure.code == "UNET_INFERENCE_FAILED"
    assert failure.stage == "wall_segmentation"
    assert failure.message == "CUDA OOM"
    assert failure.retryable is True
    assert failure.details == {"image_size": [1600, 1200]}
    assert failure.job_id == "job-1"


def test_parse_failure_missing_error_defaults_to_internal_error():
    payload = {"status": "failed", "job_id": "job-x"}
    failure = SageMakerInferenceService._parse_failure(payload, "job-x")
    assert failure.code == "INTERNAL_ERROR"
    assert failure.stage == "unknown"
    assert failure.retryable is False


@pytest.mark.parametrize(
    "container_code,expected_backend_code,expected_status",
    [
        ("INVALID_INPUT", ErrorCode.INTERNAL_SERVER_ERROR, 500),
        ("UNSUPPORTED_SCHEMA_VERSION", ErrorCode.INTERNAL_SERVER_ERROR, 500),
        ("SOURCE_IMAGE_DOWNLOAD_FAILED", ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED, 502),
        ("SOURCE_IMAGE_DECODE_FAILED", ErrorCode.INVALID_FILE_EXTENSION, 400),
        ("UNET_INFERENCE_FAILED", ErrorCode.ANALYSIS_FAILED, 502),
        ("YOLO_INFERENCE_FAILED", ErrorCode.ANALYSIS_FAILED, 502),
        ("OUTPUT_UPLOAD_FAILED", ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED, 502),
        ("INTERNAL_ERROR", ErrorCode.INTERNAL_SERVER_ERROR, 500),
    ],
)
def test_map_failure_to_app_error(
    container_code: str, expected_backend_code: ErrorCode, expected_status: int
):
    failure = SageMakerInferenceFailure(
        code=container_code, stage="x", message="m", retryable=False
    )
    err = map_failure_to_app_error(failure)
    assert isinstance(err, AppError)
    assert err.code == expected_backend_code
    assert err.status_code == expected_status
    assert "stage 'x'" in err.message


def test_map_failure_unknown_code_falls_back_to_analysis_failed():
    failure = SageMakerInferenceFailure(
        code="SOMETHING_NEW_FROM_CONTAINER",
        stage="?",
        message="?",
    )
    err = map_failure_to_app_error(failure)
    assert err.code == ErrorCode.ANALYSIS_FAILED
    assert err.status_code == 502


def test_service_unconfigured_bucket_raises_app_error():
    svc = SageMakerInferenceService(bucket="", endpoint_name="any")
    with pytest.raises(AppError) as ei:
        svc._check_configured()
    assert ei.value.code == ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED
    assert ei.value.status_code == 503


def test_service_unconfigured_endpoint_raises_app_error():
    svc = SageMakerInferenceService(bucket="b", endpoint_name="")
    with pytest.raises(AppError) as ei:
        svc._check_configured()
    assert ei.value.code == ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED
