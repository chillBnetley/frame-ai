from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.provider_settings import SecretKind

if TYPE_CHECKING:
    from app.ai.contracts import UsageInfo
    from app.repositories.provider_usage_repo import ProviderUsageRepository

logger = logging.getLogger("frame_ai.usage")


class UsageMeter:
    """Per-provider bridge between real HTTP attempts and the usage ledger.

    ``reserve`` is wired into the transport as the attempt hook: it atomically
    counts one request and raises before the send when the daily budget is spent.
    ``record`` runs after a response; it uses the reservation date captured on the
    calling thread so a request that spans UTC midnight is billed to the day it
    was started.
    """

    def __init__(
        self,
        kind: SecretKind,
        repository: ProviderUsageRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.kind = kind
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._local = threading.local()

    def reserve(self) -> None:
        reservation = self._repository.precheck_and_reserve(self.kind, self._clock())
        self._local.date = reservation.date

    def record(
        self,
        usage: UsageInfo | None,
        *,
        request_bytes: int,
        response_bytes: int,
    ) -> None:
        date = getattr(self._local, "date", None)
        self._local.date = None
        if date is None:
            # No counted attempt (for example an injected test client): nothing
            # to attach tokens to.
            return
        reported, estimated = token_counts(usage, request_bytes, response_bytes)
        # Imported at call time: app.ai's package __init__ imports the factory,
        # so a module-level import would re-enter this module during package init.
        from app.ai.errors import ProviderUsageUnavailable

        try:
            self._repository.add_tokens(
                self.kind,
                date,
                reported=reported,
                estimated=estimated,
            )
        except ProviderUsageUnavailable as exc:
            logger.warning(
                "provider_usage_token_write_failed kind=%s error_type=%s",
                self.kind,
                type(exc).__name__,
            )


def token_counts(
    usage: UsageInfo | None,
    request_bytes: int,
    response_bytes: int,
) -> tuple[int, int]:
    """Return ``(reported, estimated)`` without ever counting both."""

    if usage is not None:
        if usage.total_tokens is not None:
            return usage.total_tokens, 0
        if usage.prompt_tokens is not None and usage.completion_tokens is not None:
            return usage.prompt_tokens + usage.completion_tokens, 0
    consumed = max(0, request_bytes) + max(0, response_bytes)
    return 0, math.ceil(consumed / 4)


__all__ = ["UsageMeter", "token_counts"]
