"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Smart Parking Management System"
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://parking:parking@localhost:5432/smart_parking"
    AUTO_MIGRATE: bool = True  # run "alembic upgrade head" on startup

    # Security
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    JWT_ALGORITHM: str = "HS256"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Initial super admin (created on first start if no users exist)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Admin@123"
    ADMIN_EMAIL: str = "admin@parking.local"

    # Storage for captured vehicle / plate images
    MEDIA_DIR: Path = BASE_DIR / "media"

    # Camera workers
    CAMERA_WORKERS_ENABLED: bool = True
    PROCESS_EVERY_N_FRAMES: int = 3
    RECONNECT_MIN_SECONDS: float = 2.0
    RECONNECT_MAX_SECONDS: float = 60.0
    STREAM_JPEG_QUALITY: int = 70
    STREAM_MAX_WIDTH: int = 960

    # ANPR models
    YOLO_VEHICLE_MODEL: str = "yolov8n.pt"
    YOLO_PLATE_MODEL: str = ""  # optional dedicated licence-plate YOLO weights
    YOLO_DEVICE: str = "cpu"
    VEHICLE_CONF_THRESHOLD: float = 0.4
    OCR_LANG: str = "en"
    OCR_USE_GPU: bool = False

    # Simulation
    SIM_USE_REAL_ANPR: bool = False  # run YOLO/OCR on simulated frames instead of ground truth
    SIM_DISCONNECT_PROBABILITY: float = 0.0  # chance per minute that a simulated camera "drops"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
