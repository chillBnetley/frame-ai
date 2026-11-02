from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_prefix="FRAME_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FRAME AI API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    data_dir: Path = REPO_ROOT / "data"
    originals_dirname: str = "originals"
    registry_filename: str = "image_registry.json"

    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    content_length_allowance: int = Field(default=1024 * 1024, ge=0)

    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            expanded = REPO_ROOT / expanded
        return expanded.resolve()

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return level

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / self.originals_dirname

    @property
    def registry_path(self) -> Path:
        return self.data_dir / self.registry_filename


@lru_cache
def get_settings() -> Settings:
    return Settings()
