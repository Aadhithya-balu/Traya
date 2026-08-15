import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "TRAYA"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api"
    SECRET_KEY: str = "CHANGE_ME_traya_dev_secret_key_do_not_use_in_production"
    ENCRYPTION_KEY: str = ""  # Fernet key; auto-derived from SECRET_KEY if empty

    # Database. PostgreSQL by default; SQLite used automatically when
    # DATABASE_URL points to sqlite or is left as the local default.
    DATABASE_URL: str = "sqlite:///./traya.db"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Rate limiting (requests per window)
    RATE_LIMIT_ENABLED: bool = True
    PUBLIC_IDENTIFY_LIMIT: int = 10
    PUBLIC_IDENTIFY_WINDOW_SECONDS: int = 60
    AUTH_LIMIT: int = 30
    AUTH_WINDOW_SECONDS: int = 60

    # Uploads
    MAX_UPLOAD_BYTES: int = 6 * 1024 * 1024
    ALLOWED_IMAGE_MIMES: list[str] = ["image/jpeg", "image/png", "image/webp"]

    # Biometric engine
    BIOMETRIC_ENGINE: str = "auto"  # auto | simulation | opencv
    BIOMETRIC_ALGO_VERSION: str = "traya-pseudo-embedding-v2"
    EMBEDDING_DIM: int = 320

    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD: float = 0.82
    REVIEW_THRESHOLD: float = 0.62
    FALLBACK_FACE_THRESHOLD: float = 0.60
    CONTEXT_BOOST: float = 0.05
    SECONDARY_FEATURE_BOOST: float = 0.06

    # Sessions
    EMERGENCY_SESSION_MINUTES: int = 30
    SESSION_RETENTION_DAYS: int = 90

    # Demo
    DEMO_MODE: bool = True

    # Testing
    TESTING: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def encryption_key(self) -> bytes:
        if self.ENCRYPTION_KEY:
            return self.ENCRYPTION_KEY.encode()
        import base64
        import hashlib

        digest = hashlib.sha256(self.SECRET_KEY.encode()).digest()
        return base64.urlsafe_b64encode(digest)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
