"""AI ai_api (Sionna dev FastAPI) HTTP 클라이언트 — calibration closed-loop 용.

별도 서비스 (`ai_api` 서버) 에 한 번만 호출해서 BO best 파라미터로 실제 Sionna
시뮬을 돌린 결과(RSSI grid 또는 metrics) 를 받아옴. `CALIBRATION_AI_API_VERIFY`
env 가 truthy 일 때만 활성화.

contract 가 아직 유동적이라 응답을 dict 그대로 돌려주고 호출자가 해석.
실패는 `AiApiClientError` 로 감싸서 던지고 caller (runner) 가 swallow + log.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.core.settings import INTERNAL_API_KEY

logger = logging.getLogger(__name__)


CALIBRATION_AI_API_VERIFY_ENV = "CALIBRATION_AI_API_VERIFY"
AI_API_BASE_URL_ENV = "AI_API_BASE_URL"
# Fallback env — 기존 .env 의 AI_SERVICE_URL 도 인식 (둘 다 같은 서버를 가리키는 의도).
AI_SERVICE_URL_ENV = "AI_SERVICE_URL"
AI_API_TIMEOUT_ENV = "AI_API_TIMEOUT_SECONDS"
AI_API_DEFAULT_TIMEOUT = 600.0  # Sionna 한 회 ~ 분 단위


class AiApiClientError(RuntimeError):
    """ai_api 호출 실패 (네트워크/HTTP 에러 / 응답 파싱 등)."""


def is_closed_loop_verify_enabled() -> bool:
    return os.getenv(CALIBRATION_AI_API_VERIFY_ENV, "false").lower() in {
        "1", "true", "yes", "on"
    }


def _base_url() -> str:
    # 1순위: AI_API_BASE_URL (전용 env)
    # 2순위: AI_SERVICE_URL (web-platform .env 의 기존 키 — 같은 서버를 가리키므로 fallback)
    # 3순위: localhost:9000 (ai_api 의 기본 포트)
    raw = (
        os.getenv(AI_API_BASE_URL_ENV)
        or os.getenv(AI_SERVICE_URL_ENV)
        or "http://localhost:9000"
    )
    return raw.rstrip("/")


def _timeout() -> float:
    try:
        return float(os.getenv(AI_API_TIMEOUT_ENV, str(AI_API_DEFAULT_TIMEOUT)))
    except ValueError:
        return AI_API_DEFAULT_TIMEOUT


def run_sionna_simulation(
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """POST {AI_API_BASE_URL}/internal/sionna/run — SionnaRunRequestDto 형식.

    호출자가 이미 ai_api 의 RequestDto 형식 (engine/scene/access_point/measurement_plane/...)
    으로 payload 를 빌드해서 넘김. SageMaker 와 동등한 sync 호출이지만 Sionna 자체가
    수십초~분 단위 블로킹이므로 백그라운드 thread 에서 호출하는 게 일반적.

    예외: AiApiClientError (네트워크/HTTP/JSON 실패).
    """
    url = f"{_base_url()}/internal/sionna/run"
    headers = {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }
    logger.info("ai_api call: POST %s (local sionna backend)", url)
    try:
        with httpx.Client(timeout=_timeout()) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:3000] if exc.response is not None else ""
        logger.warning("ai_api %s — full error: %s", exc.response.status_code, body)
        raise AiApiClientError(
            f"ai_api returned {exc.response.status_code}: {body}"
        ) from exc
    except httpx.HTTPError as exc:
        raise AiApiClientError(f"ai_api request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise AiApiClientError(f"ai_api response not JSON: {exc}") from exc


def run_sionna_with_correction(
    *,
    scene_json: dict[str, Any],
    correction_profile: dict[str, Any],
    access_points: list[dict[str, Any]],
    simulation: dict[str, Any],
) -> dict[str, Any]:
    """POST {AI_API_BASE_URL}/internal/sionna/run.

    Body:
      {
        "scene": scene_json,
        "correction_profile": correction_profile,
        "access_points": [...],
        "simulation": {...}
      }

    응답은 dict 그대로 반환. 호출자가 알아서 키 추출.
    예외: AiApiClientError (네트워크 실패 / non-2xx / JSON 파싱 실패).
    """
    url = f"{_base_url()}/internal/sionna/run"
    headers = {
        "X-Internal-API-Key": INTERNAL_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "scene": scene_json,
        "correction_profile": correction_profile,
        "access_points": access_points,
        "simulation": simulation,
    }
    logger.info("ai_api call: POST %s (correction_profile keys=%s)",
                url, sorted(correction_profile.keys()))
    try:
        with httpx.Client(timeout=_timeout()) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        raise AiApiClientError(
            f"ai_api returned {exc.response.status_code}: {body}"
        ) from exc
    except httpx.HTTPError as exc:
        raise AiApiClientError(f"ai_api request failed: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise AiApiClientError(f"ai_api response not JSON: {exc}") from exc
