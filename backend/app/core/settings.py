import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
MASK_DIR = DATA_DIR / "masks"
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", str(DATA_DIR / "assets")))


def database_url() -> str:
    return DATABASE_URL


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://appuser:apppass@localhost:5432/appdb")
# DB 커넥션 풀 — 기본(5+10)은 background poller + HTTP 동시 요청에 빠듯해 늘림.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
# 세션이 풀에서 커넥션을 못 얻을 때 무한 대기 대신 N초 후 에러 (hang 가시화).
DB_POOL_TIMEOUT_SECONDS = float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "10"))
DEFAULT_DRAFT_PROJECT_NAME = os.getenv("DEFAULT_DRAFT_PROJECT_NAME", "local-upload-project").strip()
DEFAULT_DRAFT_FLOOR_NAME = os.getenv("DEFAULT_DRAFT_FLOOR_NAME", "default-floor").strip()
DEFAULT_DRAFT_SOURCE = os.getenv("DEFAULT_DRAFT_SOURCE", "local_upload").strip()
DEFAULT_DRAFT_SOURCE_MODE = os.getenv("DEFAULT_DRAFT_SOURCE_MODE", "floorplan_image").strip()
DEFAULT_DRAFT_ANALYSIS_METHOD = os.getenv("DEFAULT_DRAFT_ANALYSIS_METHOD", "fusion_service").strip()


def ai_service_url() -> str:
    return os.getenv("AI_SERVICE_URL", "http://localhost:9000").strip()

def rf_server_url() -> str:
    return os.getenv("RF_SERVER_URL", "http://localhost:9000").strip()


MEASUREMENT_LINK_TTL_SECONDS = int(os.getenv("MEASUREMENT_LINK_TTL_SECONDS", "600"))
MEASUREMENT_DEEP_LINK_SCHEME = os.getenv("MEASUREMENT_DEEP_LINK_SCHEME", "wifispace://measure").strip()
MEASUREMENT_WEB_FALLBACK_BASE_URL = os.getenv(
    "MEASUREMENT_WEB_FALLBACK_BASE_URL",
    "http://localhost:5173/mobile/measure",
).strip()
# ============================================
# Auth / JWT
# ============================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


# ============================================
# Internal API Key (AI 서버 → 백엔드 호출용)
# ============================================
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "dev-internal-key-change-me")


# ============================================
# [DEPRECATED] AWS / SageMaker — AWS 회귀 시 재사용
# ============================================
# refactor/no-aws 에서 비활성화됨. 코드 경로는 ai_api HTTP (AI_SERVICE_URL) 로 통합됐다.
# 회귀 시 sagemaker_inference_service / sagemaker_rf_inference_service / _s3 의
# raise NotImplementedError 줄을 제거하면 다시 사용 가능.
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-2").strip()
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "").strip()
SAGEMAKER_ENDPOINT_NAME = os.getenv("SAGEMAKER_ENDPOINT_NAME", "ai-inference-endpoint").strip()
SAGEMAKER_POLL_INTERVAL_SECONDS = float(os.getenv("SAGEMAKER_POLL_INTERVAL_SECONDS", "5"))
SAGEMAKER_POLL_TIMEOUT_SECONDS = float(os.getenv("SAGEMAKER_POLL_TIMEOUT_SECONDS", "900"))
SAGEMAKER_RF_ENDPOINT_NAME = os.getenv(
    "SAGEMAKER_RF_ENDPOINT_NAME", "rf-inference-async-endpoint-v1"
).strip()
RF_PRESIGNED_URL_EXPIRES_SECONDS = int(
    os.getenv("RF_PRESIGNED_URL_EXPIRES_SECONDS", "3600")
)
AWS_CONNECT_TIMEOUT_SECONDS = float(os.getenv("AWS_CONNECT_TIMEOUT_SECONDS", "5"))
AWS_READ_TIMEOUT_SECONDS = float(os.getenv("AWS_READ_TIMEOUT_SECONDS", "30"))
AWS_MAX_RETRY_ATTEMPTS = int(os.getenv("AWS_MAX_RETRY_ATTEMPTS", "2"))


# ============================================
# CORS
# ============================================
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
