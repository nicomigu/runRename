import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    STRAVA_CLIENT_ID: str
    STRAVA_CLIENT_SECRET: str
    STRAVA_VERIFY_TOKEN: str
    ANTHROPIC_API_KEY: str
    LEMON_SQUEEZY_KEY: str
    LEMON_SQUEEZY_WEBHOOK_SECRET: str = ""
    LEMON_SQUEEZY_STORE_ID: str = ""
    LEMON_SQUEEZY_VARIANT_ID: str = ""
    DATABASE_URL: str
    ADMIN_SECRET: str
    BASE_URL: str = "http://localhost:8000"
    SESSION_SECRET: str
    BETA_INVITE_CODE: str = ""

    @property
    def async_database_url(self) -> str:
        """Convert postgres:// or postgresql:// to postgresql+asyncpg://"""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
