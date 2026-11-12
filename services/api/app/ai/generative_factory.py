from __future__ import annotations

from app.ai.errors import ProviderConfigurationError
from app.ai.generative import GenerativeProvider
from app.ai.net_policy import ProviderEndpointPolicy
from app.ai.providers.generative_dashscope import DashScopeGenerativeProvider
from app.ai.providers.generative_mock import MockGenerativeProvider
from app.ai.transport import HttpTransport, PinnedHttpTransport
from app.core.config import Settings, get_settings


def build_generative_provider(
    settings: Settings | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    transport: HttpTransport | None = None,
) -> GenerativeProvider:
    """Build the generative provider from saved settings, falling back to env.

    ``provider``/``model``/``base_url``/``api_key`` override the environment so the
    in-app settings page can switch models without a restart.
    """

    resolved = settings or get_settings()
    kind = (provider or resolved.generative_provider).strip().lower()
    if kind == "mock":
        return MockGenerativeProvider()
    if kind == "dashscope":
        key = api_key
        if key is None:
            secret = resolved.generative_dashscope_api_key
            key = secret.get_secret_value() if secret is not None else ""
        if not key:
            raise ProviderConfigurationError("The DashScope generative model needs an API key.")
        policy = ProviderEndpointPolicy(
            allow_local=resolved.provider_url_policy == "allow-local",
            allow_insecure_http=resolved.provider_allow_insecure_http,
        )
        return DashScopeGenerativeProvider(
            model=model or resolved.generative_dashscope_model,
            api_key=key,
            base_url=base_url or resolved.generative_dashscope_base_url,
            transport=transport or PinnedHttpTransport(policy),
            timeout=resolved.generative_provider_timeout_seconds,
            max_retries=resolved.generative_provider_max_retries,
            download_max_bytes=resolved.generative_max_download_bytes,
        )
    raise ProviderConfigurationError(f"Unknown generative provider: {kind}.")


__all__ = ["build_generative_provider"]
