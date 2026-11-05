from __future__ import annotations

from dataclasses import dataclass

from app.ai.base import PhotographyDecisionProvider, VisionProvider
from app.ai.errors import ProviderConfigurationError
from app.ai.providers.mock import MockDecisionProvider, MockVisionProvider
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatibleVisionProvider,
)
from app.ai.transport import JsonHttpClient, UrllibJsonTransport
from app.core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    vision: VisionProvider
    decision: PhotographyDecisionProvider
    mock_reasons: tuple[str, ...]

    @property
    def is_mock(self) -> bool:
        return bool(self.mock_reasons)


def build_vision_provider(
    settings: Settings | None = None,
    *,
    client: JsonHttpClient | None = None,
) -> VisionProvider:
    resolved = settings or get_settings()
    if resolved.vision_provider == "mock":
        return MockVisionProvider(resolved.mock_scenario)

    missing = _missing_fields(
        api_key=resolved.vision_api_key.get_secret_value(),
        model=resolved.vision_model,
        base_url=resolved.vision_api_base_url,
        env_names=("FRAME_VISION_API_KEY", "FRAME_VISION_MODEL", "FRAME_VISION_API_BASE_URL"),
    )
    if missing:
        raise ProviderConfigurationError(_missing_message("vision", missing))

    return OpenAICompatibleVisionProvider(
        client or _default_client(),
        base_url=resolved.vision_api_base_url,
        api_key=resolved.vision_api_key.get_secret_value(),
        model=resolved.vision_model,
        timeout=resolved.vision_timeout,
        max_retries=resolved.vision_max_retries,
        repair_attempts=resolved.vision_repair_attempts,
    )


def build_decision_provider(
    settings: Settings | None = None,
    *,
    client: JsonHttpClient | None = None,
) -> PhotographyDecisionProvider:
    resolved = settings or get_settings()
    if resolved.decision_provider == "mock":
        return MockDecisionProvider()

    missing = _missing_fields(
        api_key=resolved.decision_api_key.get_secret_value(),
        model=resolved.decision_model,
        base_url=resolved.decision_api_base_url,
        env_names=(
            "FRAME_DECISION_API_KEY",
            "FRAME_DECISION_MODEL",
            "FRAME_DECISION_API_BASE_URL",
        ),
    )
    if missing:
        raise ProviderConfigurationError(_missing_message("decision", missing))

    return OpenAICompatibleDecisionProvider(
        client or _default_client(),
        base_url=resolved.decision_api_base_url,
        api_key=resolved.decision_api_key.get_secret_value(),
        model=resolved.decision_model,
        timeout=resolved.decision_timeout,
        max_retries=resolved.decision_max_retries,
        repair_attempts=resolved.decision_repair_attempts,
    )


def build_provider_bundle(
    settings: Settings | None = None,
    *,
    vision_client: JsonHttpClient | None = None,
    decision_client: JsonHttpClient | None = None,
) -> ProviderBundle:
    resolved = settings or get_settings()
    vision = build_vision_provider(resolved, client=vision_client)
    decision = build_decision_provider(resolved, client=decision_client)

    reasons: list[str] = []
    if vision.is_mock:
        reasons.append("vision_provider=mock")
    if decision.is_mock:
        reasons.append("decision_provider=mock")

    return ProviderBundle(
        vision=vision,
        decision=decision,
        mock_reasons=tuple(reasons),
    )


def _default_client() -> JsonHttpClient:
    return JsonHttpClient(UrllibJsonTransport())


def _missing_fields(
    *,
    api_key: str,
    model: str,
    base_url: str,
    env_names: tuple[str, str, str],
) -> list[str]:
    values = (api_key, model, base_url)
    return [name for name, value in zip(env_names, values, strict=True) if not value]


def _missing_message(kind: str, missing: list[str]) -> str:
    return (
        f"The {kind} provider is configured as 'openai' but is missing required "
        f"settings: {', '.join(missing)}."
    )


__all__ = [
    "ProviderBundle",
    "build_decision_provider",
    "build_provider_bundle",
    "build_vision_provider",
]
