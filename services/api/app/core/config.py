from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]
APP_DATA_DIRNAME = "FRAME AI"


def is_frozen() -> bool:
    """True when running from a packaged executable (PyInstaller)."""

    return bool(getattr(sys, "frozen", False))


def default_data_dir() -> Path:
    """User-writable data directory for packaged builds.

    Development keeps the repository ``data`` directory; a packaged app must
    never read or write next to its program files (the install directory is
    replaced on upgrade and may be read-only).
    """

    if not is_frozen():
        return REPO_ROOT / "data"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DATA_DIRNAME / "data"
        return Path.home() / "AppData" / "Roaming" / APP_DATA_DIRNAME / "data"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "frame-ai" / "data"
    return Path.home() / ".local" / "share" / "frame-ai" / "data"


BASE_DIR = REPO_ROOT if not is_frozen() else Path.cwd()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # A packaged app must not inherit a stray .env from the install or
        # working directory: provider keys are entered in the UI and stored in
        # the isolated user data directory instead.
        env_file=() if is_frozen() else (REPO_ROOT / ".env", ".env"),
        env_prefix="FRAME_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FRAME AI API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    data_dir: Path = Field(default_factory=default_data_dir)
    originals_dirname: str = "originals"
    registry_filename: str = "image_registry.json"
    database_filename: str = "frame.db"
    preview_dirname: str = "tmp/previews"
    export_dirname: str = "tmp/exports"
    generated_dirname: str = "generated"
    generative_results_dirname: str = "generative/results"
    generative_tmp_dirname: str = "generative/tmp"
    export_job_ttl_seconds: int = Field(default=3600, gt=0)
    export_queue_max: int = Field(default=8, ge=1)
    preview_ttl_seconds: int = Field(default=3600, gt=0)
    preview_cleanup_interval_seconds: int = Field(default=600, gt=0)
    preview_max_bytes: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    render_max_edge_default: int = Field(default=1600, gt=0)
    render_max_edge_limit: int = Field(default=2560, gt=0)
    proxy_cache_mb: int = Field(default=64, ge=0)
    mask_cache_mb: int = Field(default=64, ge=0)
    export_max_concurrency: int = Field(default=1, ge=1, le=4)
    export_max_rss_mb: int = Field(default=3072, gt=0)
    export_reserve_mb: int = Field(default=256, ge=0)
    export_denoise_simplify_pixels: int = Field(default=12_000_000, ge=1)

    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    content_length_allowance: int = Field(default=1024 * 1024, ge=0)
    max_json_body_bytes: int = Field(default=2 * 1024 * 1024, gt=0)

    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    allowed_hosts: str = "127.0.0.1,localhost,::1"

    api_auth_enabled: bool = True
    api_token_file: Path | None = None
    feature_layers: bool = Field(default=False)
    feature_semantic_masks: bool = Field(default=False)
    semantic_mask_concurrency: int = Field(default=1, ge=1, le=4)
    semantic_mask_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    rate_limit_upload: int = Field(default=0, ge=0)
    rate_limit_export: int = Field(default=0, ge=0)
    rate_limit_analysis: int = Field(default=0, ge=0)
    rate_limit_photographer: int = Field(default=0, ge=0)
    rate_limit_settings: int = Field(default=0, ge=0)
    rate_limit_render: int = Field(default=0, ge=0)
    rate_limit_default: int = Field(default=0, ge=0)

    vision_provider: Literal["mock", "openai"] = "mock"
    vision_api_key: SecretStr = SecretStr("")
    vision_model: str = ""
    vision_api_base_url: str = ""
    vision_timeout: float = Field(default=60.0, gt=0, le=600)
    vision_max_retries: int = Field(default=2, ge=0, le=10)
    vision_repair_attempts: int = Field(default=1, ge=0, le=3)

    decision_provider: Literal["mock", "openai"] = "mock"
    decision_api_key: SecretStr = SecretStr("")
    decision_model: str = ""
    decision_api_base_url: str = ""
    decision_timeout: float = Field(default=60.0, gt=0, le=600)
    decision_max_retries: int = Field(default=2, ge=0, le=10)
    decision_repair_attempts: int = Field(default=1, ge=0, le=3)

    planner_provider: Literal["mock", "openai"] | None = None
    planner_api_key: SecretStr | None = None
    planner_model: str | None = None
    planner_api_base_url: str | None = None
    planner_timeout: float | None = Field(default=None, gt=0, le=600)
    planner_max_retries: int | None = Field(default=None, ge=0, le=10)
    planner_repair_attempts: int | None = Field(default=None, ge=0, le=3)

    provider_url_policy: Literal["public-only", "allow-local"] = "public-only"
    provider_allow_insecure_http: bool = False
    provider_settings_encryption: Literal["required", "off"] = "required"
    provider_daily_request_limit: int = Field(default=0, ge=0)
    provider_daily_token_limit: int = Field(default=0, ge=0)

    mock_scenario: str = "generic"

    analysis_max_edge: int = Field(default=1024, ge=512, le=2048)
    analysis_max_concurrency: int = Field(default=2, ge=1, le=8)
    analysis_max_attempts: int = Field(default=2, ge=1, le=10)
    analysis_max_input_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    analysis_timeout_seconds: float = Field(default=600.0, gt=0)
    analysis_queue_max: int = Field(default=16, ge=1)

    photographer_max_concurrency: int = Field(default=2, ge=1, le=8)

    # V6.3 generative pipeline. The mock provider stays the default; DashScope
    # (wanx2.1-imageedit) is opt-in from the provider settings UI.
    generative_provider: Literal["mock", "dashscope"] = "mock"
    generative_dashscope_model: str = "wanx2.1-imageedit"
    generative_dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    generative_dashscope_api_key: SecretStr | None = None
    generative_daily_image_limit: int = Field(default=0, ge=0)
    generative_max_concurrency: int = Field(default=1, ge=1, le=2)
    generative_queue_max: int = Field(default=4, ge=1)
    generative_task_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    generative_max_attempts: int = Field(default=2, ge=1, le=5)
    generative_task_ttl_seconds: int = Field(default=86_400, gt=0)
    generative_result_ttl_seconds: int = Field(default=604_800, gt=0)
    generative_max_input_pixels: int = Field(default=24_000_000, gt=0)
    generative_max_output_pixels: int = Field(default=24_000_000, gt=0)
    generative_max_output_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    generative_provider_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    generative_provider_max_retries: int = Field(default=1, ge=0, le=5)
    generative_max_download_bytes: int = Field(default=96 * 1024 * 1024, gt=0)
    generative_max_outpaint_scale: float = Field(default=4.0, ge=1.0, le=16.0)
    generative_disk_budget_mb: int = Field(default=2048, ge=1)

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            expanded = BASE_DIR / expanded
        return expanded.resolve()

    @field_validator(
        "vision_model",
        "decision_model",
        "planner_model",
        "vision_api_base_url",
        "decision_api_base_url",
        "planner_api_base_url",
        "mock_scenario",
        mode="before",
    )
    @classmethod
    def _strip_provider_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("vision_api_base_url", "decision_api_base_url", "planner_api_base_url")
    @classmethod
    def _valid_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("provider base URL must be an absolute http(s) URL")
        return value.rstrip("/")

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
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / self.originals_dirname

    @property
    def registry_path(self) -> Path:
        return self.data_dir / self.registry_filename

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename

    @property
    def api_token_path(self) -> Path:
        if self.api_token_file is not None:
            return self.api_token_file.expanduser().resolve()
        return self.data_dir / "api-token"

    @property
    def mattes_dir(self) -> Path:
        return self.data_dir / "mattes"

    @property
    def semantic_models_dir(self) -> Path:
        return self.data_dir / "models" / "semantic"

    @property
    def api_rate_limits(self) -> dict[str, int]:
        return {
            "upload": self.rate_limit_upload,
            "export": self.rate_limit_export,
            "analysis": self.rate_limit_analysis,
            "photographer": self.rate_limit_photographer,
            "settings": self.rate_limit_settings,
            "render": self.rate_limit_render,
            "default": self.rate_limit_default,
        }

    @property
    def preview_dir(self) -> Path:
        return self.data_dir / self.preview_dirname

    @property
    def export_dir(self) -> Path:
        return self.data_dir / self.export_dirname

    @property
    def generated_dir(self) -> Path:
        return self.data_dir / self.generated_dirname

    @property
    def generative_results_dir(self) -> Path:
        return self.data_dir / self.generative_results_dirname

    @property
    def generative_tmp_dir(self) -> Path:
        return self.data_dir / self.generative_tmp_dirname

    @property
    def generative_disk_budget_bytes(self) -> int:
        return self.generative_disk_budget_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
