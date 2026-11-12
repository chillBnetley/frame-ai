from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic.alias_generators import to_camel

ProviderKind = Literal["mock", "openai"]
GenerativeProviderKind = Literal["mock", "dashscope"]
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


class GenerativeProviderSettingsUpdate(ProviderSettingsModel):
    """Generative image model; ``dashscope`` requires an API key to become ready."""

    provider: GenerativeProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=8192)
    clear_api_key: bool = False
    daily_image_limit: int | None = Field(default=None, ge=0, le=1000)

    @model_validator(mode="after")
    def _reject_conflicting_key_actions(self) -> GenerativeProviderSettingsUpdate:
        if self.clear_api_key and self.api_key is not None:
            if self.api_key.get_secret_value():
                raise ValueError("apiKey and clearApiKey cannot be used together")
        return self


class ProviderSettingsUpdate(ProviderSettingsModel):
    vision: ProviderEntryUpdate | None = None
    decision: ProviderEntryUpdate | None = None
    planner: PlannerProviderSettingsUpdate | None = None
    generative: GenerativeProviderSettingsUpdate | None = None


class ProviderEntryView(ProviderSettingsModel):
    provider: ProviderKind
    model: str
    base_url: str
    has_api_key: bool
    api_key_source: ApiKeySource


class PlannerProviderSettingsView(ProviderEntryView):
    """Effective planner configuration after per-field decision fallback."""


class GenerativeProviderSettingsView(ProviderSettingsModel):
    provider: GenerativeProviderKind
    model: str
    base_url: str
    has_api_key: bool
    api_key_source: ApiKeySource
    daily_image_limit: int
    ready: bool


class ProviderSettingsView(ProviderSettingsModel):
    vision: ProviderEntryView
    decision: ProviderEntryView
    planner: PlannerProviderSettingsView
    generative: GenerativeProviderSettingsView
    is_mock: bool
    has_saved_overrides: bool


class ProviderTestResult(ProviderSettingsModel):
    ok: bool
    provider: ProviderKind | GenerativeProviderKind
    model: str
    latency_ms: int
    code: str | None = None
    message: str | None = None


class ProviderTestResponse(ProviderSettingsModel):
    vision: ProviderTestResult
    decision: ProviderTestResult
    planner: ProviderTestResult
    generative: ProviderTestResult


class ProviderUsageEntry(ProviderSettingsModel):
    provider: SecretKind
    date: str
    requests: int
    tokens_estimated: int
    tokens_reported: int
    updated_at: str | None = None


class ProviderUsageView(ProviderSettingsModel):
    """Read-only daily counters; no prompt, response, image or key content."""

    date: str
    request_limit: int
    token_limit: int
    reset_at: str
    entries: list[ProviderUsageEntry]


class StoredProviderEntry(BaseModel):
    """Legacy v1 entry. Also used as the in-memory domain shape.

    The in-memory copy may hold a plaintext key while the process runs, but it
    is only serialized to disk when encryption is explicitly turned off.
    """

    model_config = ConfigDict(extra="forbid")

    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=8192)


class StoredGenerativeEntry(BaseModel):
    """In-memory generative entry; the plaintext key only lives while the process runs."""

    model_config = ConfigDict(extra="forbid")

    provider: GenerativeProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=8192)
    daily_image_limit: int | None = Field(default=None, ge=0, le=1000)


class StoredProviderSettings(BaseModel):
    """Legacy v1 document shape. Also used as the in-memory domain.

    The in-memory copy may hold a plaintext key while the process runs, but it
    is only serialized to disk when encryption is explicitly turned off.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    vision: StoredProviderEntry | None = None
    decision: StoredProviderEntry | None = None
    planner: StoredProviderEntry | None = None
    generative: StoredGenerativeEntry | None = None


SecretKind = Literal["vision", "decision", "planner", "generative"]


class StoredProviderEntryV2(BaseModel):
    """v2 entry: configuration only, never key material.

    ``extra="forbid"`` rejects a smuggled ``api_key`` field so a v1-shaped entry
    can never be written into an encrypted document.
    """

    model_config = ConfigDict(extra="forbid")

    provider: ProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)


class StoredSecret(BaseModel):
    """Base64 AES-256-GCM record: 12-byte nonce, ciphertext with a 16-byte tag."""

    model_config = ConfigDict(extra="forbid")

    alg: Literal["AES-256-GCM"] = "AES-256-GCM"
    nonce: str = Field(min_length=1, max_length=64)
    ciphertext: str = Field(min_length=1, max_length=65536)


class StoredGenerativeEntryV2(BaseModel):
    """Generative configuration only; key material lives in ``secrets``."""

    model_config = ConfigDict(extra="forbid")

    provider: GenerativeProviderKind | None = None
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=1000)
    daily_image_limit: int | None = Field(default=None, ge=0, le=1000)


class StoredProviderSettingsV2(BaseModel):
    """Encrypted document; ``secrets`` only covers providers with a saved key."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = 2
    vision: StoredProviderEntryV2 | None = None
    decision: StoredProviderEntryV2 | None = None
    planner: StoredProviderEntryV2 | None = None
    generative: StoredGenerativeEntryV2 | None = None
    secrets: dict[SecretKind, StoredSecret] = Field(default_factory=dict)


__all__ = [
    "ApiKeySource",
    "GenerativeProviderKind",
    "GenerativeProviderSettingsUpdate",
    "GenerativeProviderSettingsView",
    "PlannerProviderSettingsUpdate",
    "PlannerProviderSettingsView",
    "ProviderEntryUpdate",
    "ProviderEntryView",
    "ProviderKind",
    "ProviderSettingsUpdate",
    "ProviderSettingsView",
    "ProviderTestResponse",
    "ProviderTestResult",
    "ProviderUsageEntry",
    "ProviderUsageView",
    "SecretKind",
    "StoredGenerativeEntry",
    "StoredGenerativeEntryV2",
    "StoredProviderEntry",
    "StoredProviderEntryV2",
    "StoredProviderSettings",
    "StoredProviderSettingsV2",
    "StoredSecret",
]
