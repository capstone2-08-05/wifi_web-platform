"""S3 공용 헬퍼.

여기 helper 들은 sync (boto3 가 native sync) 라 FastAPI handler 에서 호출 시
`await run_in_threadpool(...)` 으로 감싸야 이벤트 루프 안 막힘. 짧은 작업
(presigned URL 생성, 작은 파일 upload/delete) 은 직접 호출해도 큰 문제 없음.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.aws import BOTO_CONFIG
from app.core.errors import AppError, ErrorCode
from app.core.settings import (
    AWS_REGION,
    AWS_S3_BUCKET,
    RF_PRESIGNED_URL_EXPIRES_SECONDS,
)


@lru_cache(maxsize=1)
def _client():
    return boto3.client("s3", region_name=AWS_REGION, config=BOTO_CONFIG)


def _require_bucket() -> str:
    if not AWS_S3_BUCKET:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            "AWS_S3_BUCKET not configured.",
            status_code=503,
        )
    return AWS_S3_BUCKET


def split_s3_uri(uri: str) -> tuple[str, str]:
    """s3://bucket/key/path → (bucket, 'key/path')."""
    if not uri or not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri!r}")
    rest = uri[len("s3://") :]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        raise ValueError(f"Malformed S3 URI: {uri!r}")
    return bucket, key


def build_s3_uri(key: str, bucket: Optional[str] = None) -> str:
    return f"s3://{bucket or _require_bucket()}/{key}"


def upload_bytes(
    key: str, body: bytes, content_type: Optional[str] = None
) -> str:
    """업로드 후 s3:// URI 반환."""
    bucket = _require_bucket()
    extra: dict = {}
    if content_type:
        extra["ContentType"] = content_type
    try:
        _client().put_object(Bucket=bucket, Key=key, Body=body, **extra)
    except (BotoCoreError, ClientError) as exc:
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to upload to S3: {exc}",
            status_code=502,
        ) from exc
    return build_s3_uri(key, bucket)


def delete_object(s3_uri: str) -> None:
    """S3 delete 는 idempotent (객체 없어도 200). 단, 권한/네트워크 에러는 raise."""
    try:
        bucket, key = split_s3_uri(s3_uri)
    except ValueError:
        return  # 옛 로컬 경로 등은 무시
    try:
        _client().delete_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to delete S3 object: {exc}",
            status_code=502,
        ) from exc


def download_bytes(s3_uri: str) -> bytes:
    bucket, key = split_s3_uri(s3_uri)
    try:
        obj = _client().get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            raise AppError(
                ErrorCode.UPLOADED_FILE_NOT_FOUND,
                f"S3 object not found: {s3_uri}",
                status_code=404,
            ) from exc
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to read S3 object: {exc}",
            status_code=502,
        ) from exc
    except BotoCoreError as exc:
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to read S3 object: {exc}",
            status_code=502,
        ) from exc


def presigned_get_url(
    s3_uri: str,
    expires_seconds: int = RF_PRESIGNED_URL_EXPIRES_SECONDS,
) -> str:
    bucket, key = split_s3_uri(s3_uri)
    try:
        return _client().generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=int(expires_seconds),
        )
    except (BotoCoreError, ClientError) as exc:
        raise AppError(
            ErrorCode.EXTERNAL_SERVICE_REQUEST_FAILED,
            f"Failed to generate presigned URL: {exc}",
            status_code=502,
        ) from exc
