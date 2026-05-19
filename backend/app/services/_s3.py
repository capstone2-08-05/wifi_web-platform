"""[DEPRECATED] S3 공용 헬퍼.

⚠️ AWS 회귀 시 복원: 이 파일은 모든 함수가 비활성화됐다.
   현재 자산 저장은 app/services/_local_storage.py 로 옮겨졌다.

복원 절차:
  1. 아래 raise 줄들 모두 제거 (또는 이 파일을 git 이전 revision 에서 그대로 복원)
  2. boto3 / botocore 정상 import
  3. AWS_REGION / AWS_S3_BUCKET env 재설정
  4. asset_service / scene_draft_service / measurement_service / rf_run_service 의
     `_local_storage` import 를 `_s3` 로 되돌림

옛 시그니처 (split_s3_uri / build_s3_uri / upload_bytes / delete_object /
download_bytes / presigned_get_url) 는 보존돼 있으며 raise NotImplementedError 만 한다.
"""
from __future__ import annotations

from typing import Optional


_DISABLED = (
    "_s3 module is disabled (AWS path off). Use app.services._local_storage instead. "
    "To re-enable for AWS regression, restore boto3 imports and remove these raises."
)


def split_s3_uri(uri: str) -> tuple[str, str]:
    raise NotImplementedError(_DISABLED)


def build_s3_uri(key: str, bucket: Optional[str] = None) -> str:
    raise NotImplementedError(_DISABLED)


def upload_bytes(
    key: str, body: bytes, content_type: Optional[str] = None
) -> str:
    raise NotImplementedError(_DISABLED)


def delete_object(s3_uri: str) -> None:
    raise NotImplementedError(_DISABLED)


def download_bytes(s3_uri: str) -> bytes:
    raise NotImplementedError(_DISABLED)


def presigned_get_url(s3_uri: str, expires_seconds: int = 3600) -> str:
    raise NotImplementedError(_DISABLED)
