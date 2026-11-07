from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic.alias_generators import to_camel

ProviderKind = Literal["mock", "openai"]
ApiKeySource = Literal["saved", "environment", "none"]


class ProviderSettingsModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ProviderEntryUpdate(ProviderSettingsModel):
    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def _reject_conflicting_key_actions(self) -> ProviderEntryUpdate:
        if self.clear_api_key and self.api_key is not None:
            if self.api_key.get_secret_value():
                raise ValueError("apiKey and clearApiKey cannot be used together")
        return self


class PlannerProviderSettingsUpdate(ProviderEntryUpdate):
    """Optional planner overrides; omitted or empty fields follow the decision provider."""


class ProviderSettingsUpdate(ProviderSettingsModel):
    vision: ProviderEntryUpdate | None = None
    decision: ProviderEntryUpdate | None = None
    planner: PlannerProviderSettingsUpdate | None = None


class ProviderEntryView(ProviderSettingsModel):
    provider: ProviderKind
    model: str
    base_url: str
    has_api_key: bool
    api_key_source: ApiKeySource


class PlannerProviderSettingsView(ProviderEntryView):
    """Effective planner configuration after per-field decision fallback."""


class ProviderSettingsView(ProviderSettingsModel):
    vision: ProviderEntryView
    decision: ProviderEntryView
    planner: PlannerProviderSettingsView
    is_mock: bool
    has_saved_overrides: bool


class ProviderTestResult(ProviderSettingsModel):
    ok: bool
    provider: ProviderKind
    model: str
    latency_ms: int
    code: str | None = None
    message: str | None = None


class ProviderTestResponse(ProviderSettingsModel):
    vision: ProviderTestResult
    decision: ProviderTestResult
    planner: ProviderTestResult


class StoredProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=8192)


class StoredProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    vision: StoredProviderEntry | None = None
    decision: StoredProviderEntry | None = None
    planner: StoredProviderEntry | None = None


__all__ = [
    "ApiKeySource",
    "PlannerProviderSettingsUpdate",
    "PlannerProviderSettingsView",
    "ProviderEntryUpdate",
    "ProviderEntryView",
    "ProviderKind",
    "ProviderSettingsUpdate",
    "ProviderSettingsView",
    "ProviderTestResponse",
    "ProviderTestResult",
    "StoredProviderEntry",
    "StoredProviderSettings",
]
