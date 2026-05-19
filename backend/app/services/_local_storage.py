"""로컬 디스크 기반 자산 저장소 (S3 대체).

`data/storage/` 하위에 자산을 저장하고, 백에드가 `/storage/...` 라우트로
직접 서빙. URL 은 단순 상대경로라 만료일 개념 없음 (presigned 불필요).

경로 규칙 (key):
  - assets/{project_id}/{floor_id}/{asset_id}.{ext}      — 유저 업로드 도면
  - measurement-heatmaps/{session_id}/mean.png          — GP 보간 평균
  - measurement-heatmaps/{session_id}/uncertainty.png   — GP 보간 불확실성
  - rf-heatmaps/{rf_run_id}/heatmap.png                 — Sionna 결과 렌더링
  - rf-heatmaps/{rf_run_id}/radio_map.npy               — Sionna values_dbm raw

이 모듈은 storage_url 을 "local://{key}" 형식으로 저장하고, 서빙 시에는
key 에서만 경로를 재구성한다 (레코드는 root 경로와 독립이라 휴대성 좋음).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import os

from app.core.errors import AppError, ErrorCode
from app.core.settings import DATA_DIR

logger = logging.getLogger(__name__)


STORAGE_ROOT = DATA_DIR / "storage"
LOCAL_URI_SCHEME = "local://"


def _root() -> Path:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return STORAGE_ROOT


def build_uri(key: str) -> str:
    """key → storage_url 형식."""
    if key.startswith(LOCAL_URI_SCHEME):
        return key
    return f"{LOCAL_URI_SCHEME}{key.lstrip('/')}"


def parse_uri(uri: str) -> str:
    """storage_url → key. local:// prefix 가 없으면 uri 그대로 key 로 간주."""
    if uri.startswith(LOCAL_URI_SCHEME):
        return uri[len(LOCAL_URI_SCHEME):]
    return uri


def is_local_uri(uri: str | None) -> bool:
    return bool(uri) and uri.startswith(LOCAL_URI_SCHEME)  # type: ignore[union-attr]


def static_url(key_or_uri: str) -> str:
    """프론트에게 주는 URL (절대경로). presigned 대체.

    `BACKEND_PUBLIC_URL` env 가 있으면 그걸 prefix 로, 없으면 BACKEND_PORT 기반 localhost.
    """
    key = parse_uri(key_or_uri)
    base = os.getenv("BACKEND_PUBLIC_URL", "").rstrip("/")
    if not base:
        port = os.getenv("BACKEND_PORT", "8000")
        base = f"http://localhost:{port}"
    return f"{base}/storage/{key.lstrip('/')}"


def resolve_path(key_or_uri: str) -> Path:
    """key/uri → 디스크 상 절대경로. 파일 존재 여부는 확인하지 않음."""
    key = parse_uri(key_or_uri).lstrip("/")
    return _root() / key


# ============================================================
# Write
# ============================================================
def upload_bytes(
    key: str,
    body: bytes,
    content_type: Optional[str] = None,  # 인터페이스 호환용 (로컬엔 미사용)
) -> str:
    """body 를 key 위치에 저장. 반환값은 storage_url (local://...).

    content_type 은 로컬 저장에서 쓰이지 않으나 _s3.upload_bytes 를 모방.
    """
    del content_type
    path = resolve_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to write local file {path}: {exc}",
            500,
        ) from exc
    return build_uri(key)


def delete_object(uri: str) -> None:
    """삭제 — 파일 없으면 무시. _s3.delete_object 호환."""
    try:
        path = resolve_path(uri)
    except Exception:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to delete local file %s: %s", path, exc)


# ============================================================
# Read
# ============================================================
def download_bytes(uri: str) -> bytes:
    """uri 의 파일 내용. 없으면 404."""
    path = resolve_path(uri)
    if not path.exists():
        raise AppError(
            ErrorCode.UPLOADED_FILE_NOT_FOUND,
            f"Local file not found: {uri}",
            404,
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AppError(
            ErrorCode.FILE_STORAGE_ERROR,
            f"Failed to read local file {path}: {exc}",
            500,
        ) from exc


def presigned_get_url(uri: str, expires_seconds: int = 0) -> str:
    """로컬 환경에선 만료 개념 없음 — 그냥 정적 URL 반환.

    시그니처는 _s3.presigned_get_url 와 동일하게 유지.
    """
    del expires_seconds
    return static_url(uri)
