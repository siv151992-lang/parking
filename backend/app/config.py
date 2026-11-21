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
    ANALYSIS_FPS: float = 8.0            # frames per second each real camera is analysed (the rest are skipped)
    PROCESS_EVERY_N_FRAMES: int = 1      # run YOLO on every Nth analysed frame while there is motion
    MOTION_GATE: bool = True             # skip YOLO while nothing moves in the detection zone
    MOTION_MIN_AREA: float = 0.004       # share of the zone that must change to count as motion
    STREAM_FPS: float = 6.0              # live view frame rate (frames are only drawn while someone watches)
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


INSECURE_SECRETS = {"", "change-me-in-production-use-a-long-random-string", "replace-with-a-long-random-secret"}
SECRET_FILE = BASE_DIR / ".secret_key"


def _ensure_secret_key(s: "Settings") -> None:
    """Never sign tokens with a well-known or short key. Without a proper SECRET_KEY
    a random key is generated once and kept in backend/.secret_key (owner-only)."""
    if s.SECRET_KEY not in INSECURE_SECRETS and len(s.SECRET_KEY) >= 32:
        return
    import logging
    import os
    import secrets

    try:
        key = SECRET_FILE.read_text().strip()
    except OSError:
        key = ""
    if len(key) < 32:
        key = secrets.token_urlsafe(48)
        try:
            fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
        except OSError:
            logging.getLogger("config").warning("Could not save %s: sessions end when the server restarts", SECRET_FILE)
    logging.getLogger("config").warning("SECRET_KEY is missing or insecure: using a generated key. Set SECRET_KEY in .env.")
    s.SECRET_KEY = key


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    _ensure_secret_key(s)
    s.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
