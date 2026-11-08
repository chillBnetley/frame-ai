from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import SecretStr

from app.ai.base import (
    PhotographyDecisionProvider,
    PhotographyPlannerProvider,
    VisionProvider,
)
from app.ai.errors import ProviderConfigurationError
from app.ai.net_policy import ProviderEndpointPolicy
from app.ai.providers.mock import (
    MockDecisionProvider,
    MockPlannerProvider,
    MockVisionProvider,
)
from app.ai.providers.openai_compatible import (
    OpenAICompatibleDecisionProvider,
    OpenAICompatiblePlannerProvider,
    OpenAICompatibleVisionProvider,
)
from app.ai.transport import JsonHttpClient, PinnedHttpTransport
from app.core.config import Settings, get_settings
from app.models.provider_settings import SecretKind
from app.services.usage_meter import UsageMeter


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    vision: VisionProvider
    decision: PhotographyDecisionProvider
    mock_reasons: tuple[str, ...]
    planner: PhotographyPlannerProvider = field(default_factory=MockPlannerProvider)

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

    meter = _usage_meter(resolved, "vision")
    return OpenAICompatibleVisionProvider(
        client or _default_client(resolved, meter),
        base_url=resolved.vision_api_base_url,
        api_key=resolved.vision_api_key.get_secret_value(),
        model=resolved.vision_model,
        timeout=resolved.vision_timeout,
        max_retries=resolved.vision_max_retries,
        repair_attempts=resolved.vision_repair_attempts,
        usage_meter=meter,
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

    meter = _usage_meter(resolved, "decision")
    return OpenAICompatibleDecisionProvider(
        client or _default_client(resolved, meter),
        base_url=resolved.decision_api_base_url,
        api_key=resolved.decision_api_key.get_secret_value(),
        model=resolved.decision_model,
        timeout=resolved.decision_timeout,
        max_retries=resolved.decision_max_retries,
        repair_attempts=resolved.decision_repair_attempts,
        usage_meter=meter,
    )


def build_planner_provider(
    settings: Settings | None = None,
    *,
    client: JsonHttpClient | None = None,
) -> PhotographyPlannerProvider:
    resolved = settings or get_settings()
    planner_provider = resolved.planner_provider
    provider = planner_provider or resolved.decision_provider
    if provider == "mock":
        return MockPlannerProvider()

    planner_api_key = _secret_value(resolved.planner_api_key)
    decision_api_key = _secret_value(resolved.decision_api_key)
    api_key = planner_api_key or decision_api_key
    model = resolved.planner_model or resolved.decision_model
    base_url = resolved.planner_api_base_url or resolved.decision_api_base_url
    env_names = (
        ("FRAME_PLANNER_API_KEY", "FRAME_PLANNER_MODEL", "FRAME_PLANNER_API_BASE_URL")
        if planner_provider is not None
        else ("FRAME_DECISION_API_KEY", "FRAME_DECISION_MODEL", "FRAME_DECISION_API_BASE_URL")
    )

    missing = _missing_fields(
        api_key=api_key,
        model=model,
        base_url=base_url,
        env_names=env_names,
    )
    if missing:
        raise ProviderConfigurationError(_missing_message("planner", missing))

    meter = _usage_meter(resolved, "planner")
    return OpenAICompatiblePlannerProvider(
        client or _default_client(resolved, meter),
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=(
            resolved.planner_timeout
            if resolved.planner_timeout is not None
            else resolved.decision_timeout
        ),
        max_retries=(
            resolved.planner_max_retries
            if resolved.planner_max_retries is not None
            else resolved.decision_max_retries
        ),
        repair_attempts=(
            resolved.planner_repair_attempts
            if resolved.planner_repair_attempts is not None
            else resolved.decision_repair_attempts
        ),
    )


def build_provider_bundle(
    settings: Settings | None = None,
    *,
    vision_client: JsonHttpClient | None = None,
    decision_client: JsonHttpClient | None = None,
    planner_client: JsonHttpClient | None = None,
) -> ProviderBundle:
    resolved = settings or get_settings()
    vision = build_vision_provider(resolved, client=vision_client)
    decision = build_decision_provider(resolved, client=decision_client)
    planner = build_planner_provider(resolved, client=planner_client)

    reasons: list[str] = []
    if vision.is_mock:
        reasons.append("vision_provider=mock")
    if decision.is_mock:
        reasons.append("decision_provider=mock")

    return ProviderBundle(
        vision=vision,
        decision=decision,
        mock_reasons=tuple(reasons),
        planner=planner,
    )


def _default_client(settings: Settings, meter: UsageMeter | None = None) -> JsonHttpClient:
    policy = ProviderEndpointPolicy(
        allow_local=settings.provider_url_policy == "allow-local",
        allow_insecure_http=settings.provider_allow_insecure_http,
    )
    return JsonHttpClient(
        PinnedHttpTransport(policy, on_attempt=None if meter is None else meter.reserve)
    )


def _usage_meter(settings: Settings, kind: SecretKind) -> UsageMeter:
    # Imported lazily: the repository depends on app.ai.errors, whose package
    # __init__ imports this factory, so a module-level import closes a cycle.
    from app.repositories.provider_usage_repo import ProviderUsageRepository

    return UsageMeter(
        kind,
        ProviderUsageRepository(
            settings.database_path,
            request_limit=settings.provider_daily_request_limit,
            token_limit=settings.provider_daily_token_limit,
        ),
    )


def _secret_value(secret: SecretStr | None) -> str:
    return secret.get_secret_value() if secret is not None else ""


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
    "build_planner_provider",
    "build_provider_bundle",
    "build_vision_provider",
]
