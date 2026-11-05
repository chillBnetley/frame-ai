from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import SecretStr, ValidationError

from app.ai.errors import ProviderConfigurationError, ProviderError
from app.ai.factory import ProviderBundle, build_provider_bundle
from app.ai.transport import JsonHttpClient
from app.core.config import Settings
from app.core.errors import AppError, FieldIssue, field_error_details, field_names
from app.models.provider_settings import (
    ApiKeySource,
    ProviderEntryUpdate,
    ProviderEntryView,
    ProviderKind,
    ProviderSettingsUpdate,
    ProviderSettingsView,
    ProviderTestResponse,
    ProviderTestResult,
    StoredProviderEntry,
    StoredProviderSettings,
)

logger = logging.getLogger("frame_ai.settings")

SETTINGS_FILENAME = "provider-settings.json"
TEST_TIMEOUT_SECONDS = 20.0
_KINDS = ("vision", "decision")

BundleBuilder = Callable[..., ProviderBundle]
ClientFactory = Callable[[], JsonHttpClient]


@dataclass(frozen=True, slots=True)
class _ResolvedEntry:
    provider: ProviderKind
    model: str
    base_url: str
    api_key: str
    api_key_source: ApiKeySource


class ProviderSettingsService:
    def __init__(
        self,
        base_settings: Settings,
        *,
        bundle_builder: BundleBuilder = build_provider_bundle,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._base = base_settings
        self._bundle_builder = bundle_builder
        self._client_factory = client_factory
        self._path = base_settings.data_dir / SETTINGS_FILENAME
        self._lock = threading.RLock()
        self._on_change: Callable[[ProviderBundle], None] | None = None
        self._stored = self._load()
        effective = self._effective_settings(self._stored)
        self._validate_effective(self._stored, raising=ProviderConfigurationError)
        self._bundle = self._build_bundle(effective)

    @property
    def bundle(self) -> ProviderBundle:
        with self._lock:
            return self._bundle

    def set_on_change(self, callback: Callable[[ProviderBundle], None]) -> None:
        self._on_change = callback

    def view(self) -> ProviderSettingsView:
        with self._lock:
            return self._view(self._stored)

    def apply(self, update: ProviderSettingsUpdate) -> ProviderSettingsView:
        with self._lock:
            candidate = self._merge(self._stored, update)
            effective = self._effective_settings(candidate)
            self._validate_effective(candidate, raising=AppError)
            bundle = self._build_bundle_or_error(effective)
            self._persist(candidate)
            self._stored = candidate
            self._bundle = bundle
            if self._on_change is not None:
                self._on_change(bundle)
            logger.info(
                "provider_settings_applied vision=%s decision=%s saved=%s",
                effective.vision_provider,
                effective.decision_provider,
                self._has_saved(candidate),
            )
            return self._view(candidate)

    def reset(self) -> ProviderSettingsView:
        with self._lock:
            empty = StoredProviderSettings()
            effective = self._effective_settings(empty)
            self._validate_effective(empty, raising=AppError)
            bundle = self._build_bundle_or_error(effective)
            try:
                if self._path.exists():
                    self._path.unlink()
            except OSError as exc:
                logger.error(
                    "provider_settings_reset_failed error_type=%s",
                    type(exc).__name__,
                )
                raise AppError(
                    500,
                    "provider_settings_write_failed",
                    "The saved provider settings could not be removed.",
                ) from exc
            self._stored = empty
            self._bundle = bundle
            if self._on_change is not None:
                self._on_change(bundle)
            logger.info("provider_settings_reset")
            return self._view(empty)

    def test(self, update: ProviderSettingsUpdate) -> ProviderTestResponse:
        with self._lock:
            candidate = self._merge(self._stored, update)
            effective = self._effective_settings(candidate)
            self._validate_effective(candidate, raising=AppError)
            bundle = self._build_bundle_or_error(effective)

        results: dict[str, ProviderTestResult] = {}
        for kind in _KINDS:
            provider = getattr(bundle, kind)
            provider_kind = getattr(effective, f"{kind}_provider")
            if provider.is_mock:
                results[kind] = ProviderTestResult(
                    ok=True,
                    provider=provider_kind,
                    model=provider.model,
                    latency_ms=0,
                )
                continue
            timeout = min(TEST_TIMEOUT_SECONDS, getattr(effective, f"{kind}_timeout"))
            try:
                latency_ms = provider.check_connection(timeout=timeout)
            except ProviderError as exc:
                results[kind] = ProviderTestResult(
                    ok=False,
                    provider=provider_kind,
                    model=provider.model,
                    latency_ms=0,
                    code=exc.code,
                    message=exc.message,
                )
            except Exception as exc:
                logger.warning(
                    "provider_test_failed stage=%s error_type=%s",
                    kind,
                    type(exc).__name__,
                )
                results[kind] = ProviderTestResult(
                    ok=False,
                    provider=provider_kind,
                    model=provider.model,
                    latency_ms=0,
                    code="provider_test_failed",
                    message="The provider connection test failed.",
                )
            else:
                results[kind] = ProviderTestResult(
                    ok=True,
                    provider=provider_kind,
                    model=provider.model,
                    latency_ms=latency_ms,
                )
        logger.info(
            "provider_test_completed vision_ok=%s decision_ok=%s",
            results["vision"].ok,
            results["decision"].ok,
        )
        return ProviderTestResponse(
            vision=results["vision"],
            decision=results["decision"],
        )

    def _load(self) -> StoredProviderSettings:
        if not self._path.exists():
            return StoredProviderSettings()
        try:
            raw = self._path.read_text(encoding="utf-8")
            return StoredProviderSettings.model_validate_json(raw)
        except (OSError, ValueError, ValidationError) as exc:
            logger.error(
                "provider_settings_load_failed error_type=%s",
                type(exc).__name__,
            )
            raise ProviderConfigurationError(
                "The saved provider settings could not be loaded."
            ) from exc

    def _persist(self, stored: StoredProviderSettings) -> None:
        temporary = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                stored.model_dump_json(exclude_none=True, indent=2),
                encoding="utf-8",
            )
            _restrict_permissions(temporary)
            os.replace(temporary, self._path)
            _restrict_permissions(self._path)
        except OSError as exc:
            logger.error(
                "provider_settings_persist_failed error_type=%s",
                type(exc).__name__,
            )
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise AppError(
                500,
                "provider_settings_write_failed",
                "The provider settings could not be saved.",
            ) from exc

    def _merge(
        self,
        current: StoredProviderSettings,
        update: ProviderSettingsUpdate,
    ) -> StoredProviderSettings:
        candidate = current.model_copy(deep=True)
        issues: list[FieldIssue] = []
        for kind in _KINDS:
            patch = getattr(update, kind)
            if patch is None:
                continue
            entry = (getattr(candidate, kind) or StoredProviderEntry()).model_copy(deep=True)
            issues.extend(_apply_entry_patch(kind, entry, patch))
            setattr(candidate, kind, entry)
        if issues:
            raise AppError(
                422,
                "invalid_provider_settings",
                "The provider settings contain invalid fields.",
                details=field_error_details(issues),
            )
        return candidate

    def _effective_settings(self, stored: StoredProviderSettings) -> Settings:
        updates: dict[str, Any] = {}
        for kind in _KINDS:
            entry = self._resolve(kind, stored)
            updates[f"{kind}_provider"] = entry.provider
            updates[f"{kind}_model"] = entry.model
            updates[f"{kind}_api_base_url"] = entry.base_url
            updates[f"{kind}_api_key"] = SecretStr(entry.api_key)
        return self._base.model_copy(update=updates)

    def _resolve(self, kind: str, stored: StoredProviderSettings) -> _ResolvedEntry:
        saved = getattr(stored, kind)
        provider = (
            saved.provider
            if saved and saved.provider
            else _base_value(kind, "provider", self._base)
        )
        model = _saved_or_base(saved, "model", kind, self._base)
        base_url = _saved_or_base(saved, "base_url", kind, self._base)
        environment_key = getattr(self._base, f"{kind}_api_key").get_secret_value()
        if saved is not None and saved.api_key:
            api_key = saved.api_key
            source: ApiKeySource = "saved"
        elif environment_key:
            api_key = environment_key
            source = "environment"
        else:
            api_key = ""
            source = "none"
        if provider == "mock" and not model:
            model = "mock-vision" if kind == "vision" else "mock-decision"
        return _ResolvedEntry(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_key_source=source,
        )

    def _validate_effective(
        self,
        stored: StoredProviderSettings,
        *,
        raising: type[AppError] | type[ProviderConfigurationError],
    ) -> None:
        issues: list[FieldIssue] = []
        for kind in _KINDS:
            entry = self._resolve(kind, stored)
            if entry.provider == "openai":
                if not entry.model:
                    issues.append((f"{kind}.model", "missing", "A value is required."))
                if not entry.base_url:
                    issues.append((f"{kind}.baseUrl", "missing", "A value is required."))
                if not entry.api_key:
                    issues.append((f"{kind}.apiKey", "missing", "A value is required."))
            if entry.base_url and not entry.base_url.startswith(("http://", "https://")):
                issues.append((f"{kind}.baseUrl", "invalid_url", "Must be an http(s) URL."))
            if any(character in entry.model for character in "\r\n"):
                issues.append((f"{kind}.model", "invalid_characters", "Must not contain newlines."))
            if any(character in entry.api_key for character in "\r\n"):
                issues.append(
                    (f"{kind}.apiKey", "invalid_characters", "Must not contain newlines.")
                )
        if not issues:
            return
        if raising is AppError:
            raise AppError(
                422,
                "invalid_provider_settings",
                "The provider settings contain invalid fields.",
                details=field_error_details(issues),
            )
        raise ProviderConfigurationError(
            "The provider configuration is incomplete: " + ", ".join(field_names(issues))
        )

    def _build_bundle(self, effective: Settings) -> ProviderBundle:
        if self._client_factory is None:
            return self._bundle_builder(effective)
        client = self._client_factory()
        return self._bundle_builder(
            effective,
            vision_client=client,
            decision_client=client,
        )

    def _build_bundle_or_error(self, effective: Settings) -> ProviderBundle:
        try:
            return self._build_bundle(effective)
        except ProviderConfigurationError as exc:
            raise AppError(
                422,
                "invalid_provider_settings",
                "The provider settings are incomplete.",
            ) from exc

    def _view(self, stored: StoredProviderSettings) -> ProviderSettingsView:
        entries: dict[str, ProviderEntryView] = {}
        for kind in _KINDS:
            entry = self._resolve(kind, stored)
            entries[kind] = ProviderEntryView(
                provider=entry.provider,
                model=entry.model,
                base_url=entry.base_url,
                has_api_key=bool(entry.api_key),
                api_key_source=entry.api_key_source,
            )
        is_mock = self._bundle.is_mock
        return ProviderSettingsView(
            vision=entries["vision"],
            decision=entries["decision"],
            is_mock=is_mock,
            has_saved_overrides=self._has_saved(stored),
        )

    @staticmethod
    def _has_saved(stored: StoredProviderSettings) -> bool:
        return stored.vision is not None or stored.decision is not None


def _apply_entry_patch(
    kind: str,
    entry: StoredProviderEntry,
    patch: ProviderEntryUpdate,
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    if patch.provider is not None:
        entry.provider = patch.provider
    if patch.model is not None:
        entry.model = patch.model.strip()
    if patch.base_url is not None:
        entry.base_url = patch.base_url.strip().rstrip("/")
    if patch.clear_api_key:
        entry.api_key = None
    elif patch.api_key is not None:
        secret = patch.api_key.get_secret_value()
        if secret:
            entry.api_key = secret
    if entry.model and any(character in entry.model for character in "\r\n"):
        issues.append((f"{kind}.model", "invalid_characters", "Must not contain newlines."))
    if entry.base_url and not entry.base_url.startswith(("http://", "https://")):
        issues.append((f"{kind}.baseUrl", "invalid_url", "Must be an http(s) URL."))
    if entry.api_key and any(character in entry.api_key for character in "\r\n"):
        issues.append((f"{kind}.apiKey", "invalid_characters", "Must not contain newlines."))
    return issues


def _saved_or_base(
    saved: StoredProviderEntry | None,
    attribute: Literal["model", "base_url"],
    kind: str,
    base: Settings,
) -> str:
    if saved is not None:
        value = getattr(saved, attribute)
        if value is not None:
            return str(value)
    return str(
        getattr(
            base,
            f"{kind}_{'api_base_url' if attribute == 'base_url' else attribute}",
        )
    )


def _base_value(
    kind: str,
    attribute: Literal["provider"],
    base: Settings,
) -> ProviderKind:
    return cast(ProviderKind, getattr(base, f"{kind}_{attribute}"))


def _restrict_permissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


__all__ = [
    "ProviderSettingsService",
    "SETTINGS_FILENAME",
]
