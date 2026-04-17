import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
MASK_DIR = DATA_DIR / "masks"


def database_url() -> str:
    return DATABASE_URL


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://appuser:apppass@localhost:5432/appdb")
DEFAULT_DRAFT_PROJECT_NAME = os.getenv("DEFAULT_DRAFT_PROJECT_NAME", "local-upload-project").strip()
DEFAULT_DRAFT_FLOOR_NAME = os.getenv("DEFAULT_DRAFT_FLOOR_NAME", "default-floor").strip()
DEFAULT_DRAFT_SOURCE = os.getenv("DEFAULT_DRAFT_SOURCE", "local_upload").strip()
DEFAULT_DRAFT_SOURCE_MODE = os.getenv("DEFAULT_DRAFT_SOURCE_MODE", "floorplan_image").strip()
DEFAULT_DRAFT_ANALYSIS_METHOD = os.getenv("DEFAULT_DRAFT_ANALYSIS_METHOD", "fusion_service").strip()


def ai_service_url() -> str:
    return os.getenv("AI_SERVICE_URL", "http://localhost:9000").strip()

def rf_server_url() -> str:
    return os.getenv("RF_SERVER_URL", "http://localhost:9100").strip()