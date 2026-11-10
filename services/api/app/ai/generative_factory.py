from __future__ import annotations

from app.ai.errors import ProviderConfigurationError
from app.ai.generative import GenerativeProvider
from app.ai.providers.generative_mock import MockGenerativeProvider
from app.core.config import Settings, get_settings


def build_generative_provider(settings: Settings | None = None) -> GenerativeProvider:
    resolved = settings or get_settings()
    if resolved.generative_provider == "mock":
        return MockGenerativeProvider()
    raise ProviderConfigurationError(
        f"Unknown generative provider: {resolved.generative_provider}."
    )


__all__ = ["build_generative_provider"]
