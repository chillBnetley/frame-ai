from __future__ import annotations

from typing import Any


class ProviderError(Exception):
    """A safe-to-display provider failure.

    Messages must never contain API keys, raw model responses, image bytes, or
    user filesystem paths. ``details`` is limited to structured diagnostics such
    as field locations or attempt counts.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def prefixed(self, prefix: str) -> ProviderError:
        code = self.code if self.code.startswith(f"{prefix}_") else f"{prefix}_{self.code}"
        return ProviderError(
            code,
            self.message,
            retryable=self.retryable,
            details=dict(self.details),
        )


class ProviderBudgetExceeded(ProviderError):
    """The configured daily provider budget is exhausted.

    ``details`` carries the structured ``limit/used/remaining/resetAt`` snapshot
    for synchronous 429 responses. The code is never prefixed with the calling
    stage: a budget stop is a property of the provider, not of vision/check/etc.
    """


class ProviderUsageUnavailable(ProviderError):
    """The usage ledger could not be read or written.

    Raised by the repository and surfaced as a fail-closed provider error so a
    broken ledger never turns into unbounded provider traffic.
    """


class ProviderConfigurationError(RuntimeError):
    """Raised at startup when a selected provider is missing configuration."""


__all__ = [
    "ProviderBudgetExceeded",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderUsageUnavailable",
]
