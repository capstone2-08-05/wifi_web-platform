"""boto3 공통 설정.

AWS 호출이 무한정 hang 하면 그 호출을 감싼 DB 세션/스레드가 같이 묶여
커넥션 풀이 고갈된다. 모든 boto3 client 는 bounded timeout + retry 로 생성.
"""
from __future__ import annotations

from botocore.config import Config

from app.core.settings import (
    AWS_CONNECT_TIMEOUT_SECONDS,
    AWS_MAX_RETRY_ATTEMPTS,
    AWS_READ_TIMEOUT_SECONDS,
)

# 모든 boto3 client 에 공통 적용. 호출이 (connect+read+retry) 안에 반드시 끝나거나 실패.
BOTO_CONFIG = Config(
    connect_timeout=AWS_CONNECT_TIMEOUT_SECONDS,
    read_timeout=AWS_READ_TIMEOUT_SECONDS,
    retries={"max_attempts": AWS_MAX_RETRY_ATTEMPTS, "mode": "standard"},
)
