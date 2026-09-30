import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/, not backend/app/. This is three `.parent`s from a file at
# app/config/settings.py. It was two, which resolved to backend/app and meant
# the app looked for backend/app/.env - a file that has never existed - so every
# documented instruction to set a value in backend/.env silently did nothing.
# Settings were always falling back to the defaults below.
BASE_DIR = Path(__file__).resolve().parents[2]


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

    # Database. Supabase/PostgreSQL is the production primary; SQLite is the
    # demo and development fallback (see app/database/service.py).
    DATABASE_URL: str = "sqlite:///./traya.db"
    DATABASE_FALLBACK_URL: str = ""
    # Opt-in, and off by default. A configured-but-unreachable primary must fail
    # startup, not quietly run against an unbacked local file. This does not
    # affect the zero-config demo: when DATABASE_URL is already SQLite the
    # fallback path is never consulted at all.
    DATABASE_ALLOW_FALLBACK: bool = False
    DATABASE_PROBE_TIMEOUT_SECONDS: float = 3.0
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # The 20-character project ref. Recorded so Phase 4 can build RLS and
    # storage policies without asking for it again. Nothing reads it yet, and
    # it is declared here rather than left loose in `.env` on purpose: a key the
    # app ignores is a key someone will assume is working.
    SUPABASE_PROJECT_REF: str = ""

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
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith(("postgresql", "postgres+"))

    @property
    def uses_supabase(self) -> bool:
        """True when the primary points at a Supabase project.

        Supabase URLs are pooled connection strings carrying the project ref
        as the host, e.g. ``aws-0-ap-south-1.pooler.supabase.com``.
        """
        return self.is_postgres and "supabase" in self.DATABASE_URL

    @property
    def effective_fallback_url(self) -> str:
        return self.DATABASE_FALLBACK_URL or "sqlite:///./traya.db"

    def masked_database_url(self) -> str:
        """Connection string with any password replaced, for status output."""
        url = self.DATABASE_URL
        if "@" not in url or "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        credentials, host = rest.split("@", 1)
        user = credentials.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"

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
