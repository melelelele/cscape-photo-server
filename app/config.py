from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CSCape Photo Verification Service"
    environment: str = "production"

    database_url: str
    cscape_api_key: str = Field(min_length=32)
    public_base_url: str

    xai_api_key: str = Field(min_length=1)
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.5"
    xai_timeout_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    xai_image_detail: str = "high"

    max_upload_bytes: int = Field(default=8 * 1024 * 1024, ge=1_000_000, le=20 * 1024 * 1024)
    max_image_dimension: int = Field(default=1600, ge=640, le=4096)
    jpeg_quality: int = Field(default=85, ge=60, le=95)
    default_task_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)

    @field_validator("public_base_url", "xai_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("xai_image_detail")
    @classmethod
    def validate_image_detail(cls, value: str) -> str:
        if value not in {"low", "high", "auto"}:
            raise ValueError("XAI_IMAGE_DETAIL must be low, high, or auto")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
