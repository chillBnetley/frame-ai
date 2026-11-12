from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import SecretStr, ValidationError

from app.ai.errors import ProviderConfigurationError, ProviderError
from app.ai.factory import ProviderBundle, build_provider_bundle
from app.ai.generative import GenerativeProviderError
from app.ai.generative_factory import build_generative_provider
from app.ai.net_policy import (
    EndpointPolicyError,
    ProviderEndpointPolicy,
    parse_endpoint,
    validate_for_save,
    validate_host_for_save,
)
from app.ai.transport import JsonHttpClient
from app.core.config import Settings
from app.core.errors import AppError, FieldIssue, field_error_details, field_names
from app.models.provider_settings import (
    ApiKeySource,
    GenerativeProviderKind,
    GenerativeProviderSettingsUpdate,
    GenerativeProviderSettingsView,
    PlannerProviderSettingsView,
    ProviderEntryUpdate,
    ProviderEntryView,
    ProviderKind,
    ProviderSettingsUpdate,
    ProviderSettingsView,
    ProviderTestResponse,
    ProviderTestResult,
    SecretKind,
    StoredGenerativeEntry,
    StoredGenerativeEntryV2,
    StoredProviderEntry,
    StoredProviderEntryV2,
    StoredProviderSettings,
    StoredProviderSettingsV2,
    StoredSecret,
)
from app.services.secret_store import (
    SecretBox,
    SecretStoreError,
    blob_from_record,
    blob_to_record,
    default_master_key_store,
    provider_settings_aad,
    write_private_document,
)

logger = logging.getLogger("frame_ai.settings")

SETTINGS_FILENAME = "provider-settings.json"
TEST_TIMEOUT_SECONDS = 20.0
_DECRYPTED_KEY_MESSAGE = (
    "The saved provider API key could not be decrypted. Re-enter the API key in model settings."
)
_KINDS: tuple[SecretKind, ...] = ("vision", "decision", "planner")
_FALLBACK_KINDS = {"planner": "decision"}
_GENERATIVE_SECRET_KIND: SecretKind = "generative"
_DEFAULT_GENERATIVE_MODEL = "wanx2.1-imageedit"
_DEFAULT_GENERATIVE_BASE_URL = "https://dashscope.aliyuncs.com"
_MOCK_MODELS: dict[str, str] = {
    "vision": "mock-vision",
    "decision": "mock-decision",
    "planner": "mock-planner",
}
_NUMERIC_FIELDS = ("timeout", "max_retries", "repair_attempts")

BundleBuilder = Callable[..., ProviderBundle]
ClientFactory = Callable[[], JsonHttpClient]


@dataclass(frozen=True, slots=True)
class _ResolvedEntry:
    provider: ProviderKind
    model: str
    base_url: str
    api_key: str
    api_key_source: ApiKeySource


@dataclass(frozen=True, slots=True)
class ResolvedGenerative:
    """Effective generative image model configuration."""

    provider: GenerativeProviderKind
    model: str
    base_url: str
    api_key: str
    api_key_source: ApiKeySource
    daily_image_limit: int

    @property
    def ready(self) -> bool:
        return self.provider == "mock" or bool(self.api_key)


GenerativeChangeCallback = Callable[[ResolvedGenerative], None]


class ProviderSettingsService:
    def __init__(
        self,
        base_settings: Settings,
        *,
        bundle_builder: BundleBuilder = build_provider_bundle,
        client_factory: ClientFactory | None = None,
        secret_box: SecretBox | None = None,
    ) -> None:
        self._base = base_settings
        self._bundle_builder = bundle_builder
        self._client_factory = client_factory
        self._path = base_settings.data_dir / SETTINGS_FILENAME
        self._lock = threading.RLock()
        self._on_change: Callable[[ProviderBundle], None] | None = None
        self._on_generative_change: GenerativeChangeCallback | None = None
        self._encryption = base_settings.provider_settings_encryption
        self._secret_box = secret_box
        # Read and parse once: deciding whether a key may be created and loading
        # the settings must observe the same document, even if the file changes
        # concurrently after startup begins.
        exists, document, document_error = self._read_document()
        self._allow_key_create = self._may_create_master_key(exists, document, document_error)
        self._stored, legacy_document = self._load(exists, document, document_error)
        effective = self._effective_settings(self._stored)
        self._validate_effective(self._stored, raising=ProviderConfigurationError)
        self._bundle = self._build_bundle(effective)
        if self._encryption == "off":
            logger.warning("provider_settings_encryption_disabled mode=off")
        elif legacy_document:
            # Migration runs only after the v1 document passed validation and the
            # bundle was built; a failure here leaves the v1 bytes untouched.
            self._persist(self._stored, startup=True)
            logger.info("provider_settings_migrated from=1 to=2")

    @property
    def bundle(self) -> ProviderBundle:
        with self._lock:
            return self._bundle

    @property
    def _secrets(self) -> SecretBox:
        """Resolved lazily so the platform key store is only touched when needed."""

        if self._secret_box is None:
            self._secret_box = SecretBox(
                default_master_key_store(
                    self._base.data_dir,
                    allow_create=self._allow_key_create,
                )
            )
        return self._secret_box

    def _read_document(self) -> tuple[bool, Any, Exception | None]:
        """Return ``(exists, document, error)`` with a single file read."""

        if not self._path.exists():
            return False, None, None
        try:
            return True, json.loads(self._path.read_text(encoding="utf-8")), None
        except (OSError, ValueError) as exc:
            return True, None, exc

    def _may_create_master_key(
        self,
        exists: bool,
        document: Any,
        error: Exception | None,
    ) -> bool:
        """Forbid minting a key when the stored document already holds ciphertext.

        A missing master key must mean "re-enter the API keys", never "generate a
        replacement". A v2 document without any ``secrets`` (or a legacy v1 file,
        or no file at all) has nothing to decrypt, so the first key may still be
        created normally.
        """

        if not exists:
            return True
        if error is not None:
            # Unreadable documents fail closed in _load() before any crypto runs.
            return False
        if not isinstance(document, dict) or document.get("version") != 2:
            return True
        secrets = document.get("secrets")
        return not isinstance(secrets, dict) or not secrets

    def set_on_change(self, callback: Callable[[ProviderBundle], None]) -> None:
        self._on_change = callback

    def set_on_generative_change(self, callback: GenerativeChangeCallback) -> None:
        self._on_generative_change = callback

    def generative_config(self) -> ResolvedGenerative:
        with self._lock:
            return self._resolve_generative(self._stored)

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
            if self._on_generative_change is not None:
                self._on_generative_change(self._resolve_generative(candidate))
            logger.info(
                "provider_settings_applied vision=%s decision=%s planner=%s saved=%s",
                effective.vision_provider,
                effective.decision_provider,
                effective.planner_provider,
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
            if self._on_generative_change is not None:
                self._on_generative_change(self._resolve_generative(empty))
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
            "provider_test_completed vision_ok=%s decision_ok=%s planner_ok=%s",
            results["vision"].ok,
            results["decision"].ok,
            results["planner"].ok,
        )
        generative_result = self._test_generative(candidate)
        logger.info("provider_test_completed generative_ok=%s", generative_result.ok)
        return ProviderTestResponse(
            vision=results["vision"],
            decision=results["decision"],
            planner=results["planner"],
            generative=generative_result,
        )

    def _test_generative(self, candidate: StoredProviderSettings) -> ProviderTestResult:
        config = self._resolve_generative(candidate)
        try:
            provider = build_generative_provider(
                self._base,
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                api_key=config.api_key or None,
            )
        except ProviderConfigurationError:
            return ProviderTestResult(
                ok=False,
                provider=config.provider,
                model=config.model,
                latency_ms=0,
                code="generative_provider_not_configured",
                message="The generative model has no usable API key.",
            )
        if provider.is_mock:
            return ProviderTestResult(
                ok=True,
                provider=config.provider,
                model=provider.model,
                latency_ms=0,
            )
        timeout = min(TEST_TIMEOUT_SECONDS, self._base.generative_provider_timeout_seconds)
        try:
            latency_ms = provider.check_connection(timeout=timeout)
        except GenerativeProviderError as exc:
            return ProviderTestResult(
                ok=False,
                provider=config.provider,
                model=provider.model,
                latency_ms=0,
                code=exc.code,
                message=exc.message,
            )
        except Exception as exc:
            logger.warning(
                "provider_test_failed stage=generative error_type=%s",
                type(exc).__name__,
            )
            return ProviderTestResult(
                ok=False,
                provider=config.provider,
                model=provider.model,
                latency_ms=0,
                code="provider_test_failed",
                message="The provider connection test failed.",
            )
        return ProviderTestResult(
            ok=True,
            provider=config.provider,
            model=provider.model,
            latency_ms=latency_ms,
        )

    def _load(
        self,
        exists: bool,
        document: Any,
        error: Exception | None,
    ) -> tuple[StoredProviderSettings, bool]:
        """Return the in-memory domain plus whether a legacy v1 file needs migration."""

        if not exists:
            return StoredProviderSettings(), False
        if error is not None:
            logger.error(
                "provider_settings_load_failed error_type=%s",
                type(error).__name__,
            )
            raise ProviderConfigurationError(
                "The saved provider settings could not be loaded."
            ) from None
        if not isinstance(document, dict):
            raise ProviderConfigurationError("The saved provider settings could not be loaded.")
        version = document.get("version", 1)
        if version == 2:
            return self._load_v2(document), False
        if version != 1 or isinstance(version, bool):
            logger.error("provider_settings_load_failed error_type=UnsupportedVersion")
            raise ProviderConfigurationError(
                "The saved provider settings use an unsupported format version."
            )
        try:
            return StoredProviderSettings.model_validate(document), True
        except ValidationError as exc:
            logger.error(
                "provider_settings_load_failed error_type=%s",
                type(exc).__name__,
            )
            raise ProviderConfigurationError(
                "The saved provider settings could not be loaded."
            ) from None

    def _load_v2(self, document: dict[str, Any]) -> StoredProviderSettings:
        try:
            parsed = StoredProviderSettingsV2.model_validate(document)
        except ValidationError as exc:
            logger.error(
                "provider_settings_load_failed error_type=%s",
                type(exc).__name__,
            )
            raise ProviderConfigurationError(
                "The saved provider settings could not be loaded."
            ) from None
        entries: dict[str, StoredProviderEntry | None] = {}
        for kind in _KINDS:
            entry = getattr(parsed, kind)
            record = parsed.secrets.get(kind)
            # Rebuilding the domain entry validates the decrypted plaintext, so it
            # belongs inside the same boundary: a pydantic ValidationError would
            # otherwise echo the key prefix through ``input_value``.
            try:
                api_key: str | None = None
                if record is not None:
                    blob = blob_from_record(record.alg, record.nonce, record.ciphertext)
                    api_key = self._secrets.decrypt(blob, provider_settings_aad(kind))
                if entry is None and api_key is None:
                    entries[kind] = None
                    continue
                entries[kind] = StoredProviderEntry(
                    provider=entry.provider if entry is not None else None,
                    model=entry.model if entry is not None else None,
                    base_url=entry.base_url if entry is not None else None,
                    api_key=api_key,
                )
            except SecretStoreError as exc:
                logger.error(
                    "provider_settings_decrypt_failed kind=%s error_type=%s",
                    kind,
                    type(exc).__name__,
                )
                raise ProviderConfigurationError(str(exc)) from None
            except ValidationError as exc:
                logger.error(
                    "provider_settings_decrypt_failed kind=%s error_type=%s",
                    kind,
                    type(exc).__name__,
                )
                raise ProviderConfigurationError(_DECRYPTED_KEY_MESSAGE) from None
        generative = self._load_generative_v2(parsed)
        try:
            return StoredProviderSettings.model_validate({**entries, "generative": generative})
        except ValidationError as exc:
            logger.error(
                "provider_settings_load_failed error_type=%s",
                type(exc).__name__,
            )
            raise ProviderConfigurationError(
                "The saved provider settings could not be loaded."
            ) from None

    def _load_generative_v2(
        self,
        parsed: StoredProviderSettingsV2,
    ) -> StoredGenerativeEntry | None:
        entry = parsed.generative
        record = parsed.secrets.get(_GENERATIVE_SECRET_KIND)
        try:
            api_key: str | None = None
            if record is not None:
                blob = blob_from_record(record.alg, record.nonce, record.ciphertext)
                api_key = self._secrets.decrypt(
                    blob,
                    provider_settings_aad(_GENERATIVE_SECRET_KIND),
                )
            if entry is None and api_key is None:
                return None
            return StoredGenerativeEntry(
                provider=entry.provider if entry is not None else None,
                model=entry.model if entry is not None else None,
                base_url=entry.base_url if entry is not None else None,
                daily_image_limit=entry.daily_image_limit if entry is not None else None,
                api_key=api_key,
            )
        except SecretStoreError as exc:
            logger.error(
                "provider_settings_decrypt_failed kind=%s error_type=%s",
                _GENERATIVE_SECRET_KIND,
                type(exc).__name__,
            )
            raise ProviderConfigurationError(str(exc)) from None
        except ValidationError:
            logger.error(
                "provider_settings_decrypt_failed kind=%s error_type=ValidationError",
                _GENERATIVE_SECRET_KIND,
            )
            raise ProviderConfigurationError(_DECRYPTED_KEY_MESSAGE) from None

    def _persist(self, stored: StoredProviderSettings, *, startup: bool = False) -> None:
        try:
            payload = self._serialize(stored)
        except SecretStoreError as exc:
            logger.error(
                "provider_settings_encrypt_failed error_type=%s",
                type(exc).__name__,
            )
            raise _persist_error(startup, "secret_store_error", str(exc)) from None
        try:
            write_private_document(self._path, payload)
        except OSError as exc:
            logger.error(
                "provider_settings_persist_failed error_type=%s",
                type(exc).__name__,
            )
            raise _persist_error(
                startup,
                "provider_settings_write_failed",
                "The provider settings could not be saved.",
            ) from None

    def _serialize(self, stored: StoredProviderSettings) -> bytes:
        """Build the whole document in memory; no file is touched on failure."""

        if self._encryption == "off":
            logger.warning("provider_settings_plaintext_write mode=off")
            return stored.model_dump_json(exclude_none=True, indent=2).encode("utf-8")
        entries: dict[str, StoredProviderEntryV2 | None] = {}
        secrets: dict[SecretKind, StoredSecret] = {}
        for kind in _KINDS:
            entry = getattr(stored, kind)
            if entry is None:
                entries[kind] = None
                continue
            entries[kind] = StoredProviderEntryV2(
                provider=entry.provider,
                model=entry.model,
                base_url=entry.base_url,
            )
            if entry.api_key:
                blob = self._secrets.encrypt(entry.api_key, provider_settings_aad(kind))
                secrets[kind] = StoredSecret.model_validate(blob_to_record(blob))
        generative_entry: StoredGenerativeEntryV2 | None = None
        saved_generative = stored.generative
        if saved_generative is not None:
            generative_entry = StoredGenerativeEntryV2(
                provider=saved_generative.provider,
                model=saved_generative.model,
                base_url=saved_generative.base_url,
                daily_image_limit=saved_generative.daily_image_limit,
            )
            if saved_generative.api_key:
                blob = self._secrets.encrypt(
                    saved_generative.api_key,
                    provider_settings_aad(_GENERATIVE_SECRET_KIND),
                )
                secrets[_GENERATIVE_SECRET_KIND] = StoredSecret.model_validate(
                    blob_to_record(blob)
                )
        document = StoredProviderSettingsV2(
            vision=entries["vision"],
            decision=entries["decision"],
            planner=entries["planner"],
            generative=generative_entry,
            secrets=secrets,
        )
        return document.model_dump_json(exclude_none=True, indent=2).encode("utf-8")

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
            issues.extend(_apply_entry_patch(kind, entry, patch, self._policy()))
            setattr(candidate, kind, entry)
        if update.generative is not None:
            generative = (candidate.generative or StoredGenerativeEntry()).model_copy(deep=True)
            issues.extend(_apply_generative_patch(generative, update.generative, self._policy()))
            candidate.generative = generative
        if issues:
            raise AppError(
                422,
                "invalid_provider_settings",
                "The provider settings contain invalid fields.",
                details=field_error_details(issues),
            )
        return candidate

    def _policy(self) -> ProviderEndpointPolicy:
        return ProviderEndpointPolicy(
            allow_local=self._base.provider_url_policy == "allow-local",
            allow_insecure_http=self._base.provider_allow_insecure_http,
        )

    def _effective_settings(self, stored: StoredProviderSettings) -> Settings:
        updates: dict[str, Any] = {}
        for kind in _KINDS:
            entry = self._resolve(kind, stored)
            updates[f"{kind}_provider"] = entry.provider
            updates[f"{kind}_model"] = entry.model
            updates[f"{kind}_api_base_url"] = entry.base_url
            updates[f"{kind}_api_key"] = SecretStr(entry.api_key)
            for attribute in _NUMERIC_FIELDS:
                value = getattr(self._base, f"{kind}_{attribute}")
                if value is None and kind in _FALLBACK_KINDS:
                    value = getattr(self._base, f"{_FALLBACK_KINDS[kind]}_{attribute}")
                updates[f"{kind}_{attribute}"] = value
        generative = self._resolve_generative(stored)
        updates["generative_provider"] = generative.provider
        updates["generative_dashscope_model"] = generative.model
        updates["generative_dashscope_base_url"] = generative.base_url
        updates["generative_dashscope_api_key"] = (
            SecretStr(generative.api_key) if generative.api_key else None
        )
        updates["generative_daily_image_limit"] = generative.daily_image_limit
        return self._base.model_copy(update=updates)

    def _resolve(self, kind: str, stored: StoredProviderSettings) -> _ResolvedEntry:
        if kind == "planner":
            return self._resolve_planner(stored)
        return self._resolve_kind(kind, stored)

    def _resolve_generative(self, stored: StoredProviderSettings) -> ResolvedGenerative:
        saved = stored.generative
        provider: GenerativeProviderKind = (
            saved.provider
            if saved is not None and saved.provider is not None
            else self._base.generative_provider
        )
        model = (
            saved.model
            if saved is not None and saved.model
            else self._base.generative_dashscope_model or _DEFAULT_GENERATIVE_MODEL
        )
        base_url = (
            saved.base_url
            if saved is not None and saved.base_url
            else self._base.generative_dashscope_base_url or _DEFAULT_GENERATIVE_BASE_URL
        )
        environment_key = _secret_value(self._base.generative_dashscope_api_key)
        if saved is not None and saved.api_key:
            api_key = saved.api_key
            source: ApiKeySource = "saved"
        elif environment_key:
            api_key = environment_key
            source = "environment"
        else:
            api_key = ""
            source = "none"
        limit = (
            saved.daily_image_limit
            if saved is not None and saved.daily_image_limit is not None
            else self._base.generative_daily_image_limit
        )
        return ResolvedGenerative(
            provider=provider,
            model=model,
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            api_key_source=source,
            daily_image_limit=limit,
        )

    def _resolve_kind(self, kind: str, stored: StoredProviderSettings) -> _ResolvedEntry:
        saved = getattr(stored, kind)
        provider = (
            saved.provider
            if saved and saved.provider
            else _base_value(kind, "provider", self._base)
        )
        model = _saved_or_base(saved, "model", kind, self._base)
        base_url = _saved_or_base(saved, "base_url", kind, self._base)
        environment_key = _base_api_key(kind, self._base)
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
            model = _MOCK_MODELS[kind]
        return _ResolvedEntry(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_key_source=source,
        )

    def _resolve_planner(self, stored: StoredProviderSettings) -> _ResolvedEntry:
        decision = self._resolve_kind("decision", stored)
        decision_model = _saved_or_base(stored.decision, "model", "decision", self._base)
        saved = stored.planner
        provider = (
            saved.provider
            if saved and saved.provider
            else (self._base.planner_provider or decision.provider)
        )
        model = (
            saved.model if saved and saved.model else (self._base.planner_model or decision_model)
        )
        base_url = (
            saved.base_url
            if saved and saved.base_url
            else (self._base.planner_api_base_url or decision.base_url)
        )
        planner_key = _secret_value(self._base.planner_api_key)
        if saved is not None and saved.api_key:
            api_key = saved.api_key
            source: ApiKeySource = "saved"
        elif planner_key:
            api_key = planner_key
            source = "environment"
        else:
            api_key = decision.api_key
            source = decision.api_key_source
        if provider == "mock":
            model = saved.model if saved is not None and saved.model else _MOCK_MODELS["planner"]
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
            if entry.base_url:
                try:
                    validate_for_save(parse_endpoint(entry.base_url), self._policy())
                except EndpointPolicyError:
                    issues.append(
                        (
                            f"{kind}.baseUrl",
                            "invalid_url",
                            "Must be an allowed http(s) URL.",
                        )
                    )
            if any(character in entry.model for character in "\r\n"):
                issues.append((f"{kind}.model", "invalid_characters", "Must not contain newlines."))
            if any(character in entry.api_key for character in "\r\n"):
                issues.append(
                    (f"{kind}.apiKey", "invalid_characters", "Must not contain newlines.")
                )
        generative = self._resolve_generative(stored)
        if generative.provider == "dashscope" and not generative.api_key:
            issues.append(
                (
                    "generative.apiKey",
                    "missing",
                    "A DashScope API key is required for the generative model.",
                )
            )
        if any(character in generative.model for character in "\r\n"):
            issues.append(
                ("generative.model", "invalid_characters", "Must not contain newlines.")
            )
        if generative.base_url:
            try:
                validate_for_save(parse_endpoint(generative.base_url), self._policy())
            except EndpointPolicyError:
                issues.append(
                    (
                        "generative.baseUrl",
                        "invalid_url",
                        "Must be an allowed http(s) URL.",
                    )
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
            planner_client=client,
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
        planner_entry = entries["planner"]
        generative = self._resolve_generative(stored)
        is_mock = self._bundle.is_mock
        return ProviderSettingsView(
            vision=entries["vision"],
            decision=entries["decision"],
            planner=PlannerProviderSettingsView(
                provider=planner_entry.provider,
                model=planner_entry.model,
                base_url=planner_entry.base_url,
                has_api_key=planner_entry.has_api_key,
                api_key_source=planner_entry.api_key_source,
            ),
            generative=GenerativeProviderSettingsView(
                provider=generative.provider,
                model=generative.model,
                base_url=generative.base_url,
                has_api_key=bool(generative.api_key),
                api_key_source=generative.api_key_source,
                daily_image_limit=generative.daily_image_limit,
                ready=generative.ready,
            ),
            is_mock=is_mock,
            has_saved_overrides=self._has_saved(stored),
        )

    @staticmethod
    def _has_saved(stored: StoredProviderSettings) -> bool:
        return (
            stored.vision is not None
            or stored.decision is not None
            or stored.planner is not None
            or stored.generative is not None
        )


def _apply_generative_patch(
    entry: StoredGenerativeEntry,
    patch: GenerativeProviderSettingsUpdate,
    policy: ProviderEndpointPolicy,
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    if patch.provider is not None:
        entry.provider = patch.provider
    if patch.model is not None:
        entry.model = patch.model.strip()
    if patch.base_url is not None:
        entry.base_url = patch.base_url.strip().rstrip("/")
    if patch.daily_image_limit is not None:
        entry.daily_image_limit = patch.daily_image_limit
    if patch.clear_api_key:
        entry.api_key = None
    elif patch.api_key is not None:
        secret = patch.api_key.get_secret_value()
        if secret:
            entry.api_key = secret
    if entry.model and any(character in entry.model for character in "\r\n"):
        issues.append(("generative.model", "invalid_characters", "Must not contain newlines."))
    if entry.base_url:
        try:
            endpoint = parse_endpoint(entry.base_url)
            validate_for_save(endpoint, policy)
            validate_host_for_save(endpoint.host)
        except EndpointPolicyError:
            issues.append(
                ("generative.baseUrl", "invalid_url", "Must be an allowed http(s) URL.")
            )
    if entry.api_key and any(character in entry.api_key for character in "\r\n"):
        issues.append(("generative.apiKey", "invalid_characters", "Must not contain newlines."))
    return issues


def _apply_entry_patch(
    kind: str,
    entry: StoredProviderEntry,
    patch: ProviderEntryUpdate,
    policy: ProviderEndpointPolicy,
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
    if entry.base_url:
        try:
            endpoint = parse_endpoint(entry.base_url)
            validate_for_save(endpoint, policy)
            validate_host_for_save(endpoint.host)
        except EndpointPolicyError:
            issues.append(
                (
                    f"{kind}.baseUrl",
                    "invalid_url",
                    "Must be an allowed http(s) URL.",
                )
            )
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
        if value:
            return str(value)
    attribute_name = "api_base_url" if attribute == "base_url" else attribute
    value = getattr(base, f"{kind}_{attribute_name}")
    return "" if value is None else str(value)


def _base_value(
    kind: str,
    attribute: Literal["provider"],
    base: Settings,
) -> ProviderKind:
    return cast(ProviderKind, getattr(base, f"{kind}_{attribute}"))


def _base_api_key(kind: str, base: Settings) -> str:
    return _secret_value(getattr(base, f"{kind}_api_key"))


def _secret_value(secret: SecretStr | None) -> str:
    return secret.get_secret_value() if secret is not None else ""


def _persist_error(startup: bool, code: str, message: str) -> Exception:
    """Startup failures must abort the process; request failures stay HTTP 500."""

    if startup:
        return ProviderConfigurationError(message)
    return AppError(500, code, message)


__all__ = [
    "ProviderSettingsService",
    "SETTINGS_FILENAME",
]
