from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.settings import settings


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = settings.DATABASE_URL


def get_database_url() -> str:
    return Config().database_url
