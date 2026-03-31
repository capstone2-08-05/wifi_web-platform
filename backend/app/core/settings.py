import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
MASK_DIR = DATA_DIR / "masks"


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://appuser:apppass@localhost:5432/appdb")


def ai_service_url() -> str:
    return os.getenv("AI_SERVICE_URL", "").strip()


def rf_server_url() -> str:
    return os.getenv("RF_SERVER_URL", "").strip()
