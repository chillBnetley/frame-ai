from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from app.ai.errors import ProviderBudgetExceeded, ProviderUsageUnavailable
from app.models.provider_settings import SecretKind
from app.repositories.db import connect

_USAGE_UNAVAILABLE_CODE = "provider_usage_unavailable"
_USAGE_UNAVAILABLE_MESSAGE = "The provider usage ledger is unavailable."
_BUDGET_MESSAGE = "The daily model usage limit has been reached."


def _usage_unavailable() -> ProviderUsageUnavailable:
    return ProviderUsageUnavailable(
        _USAGE_UNAVAILABLE_CODE,
        _USAGE_UNAVAILABLE_MESSAGE,
        retryable=False,
    )


@dataclass(frozen=True, slots=True)
class UsageRow:
    date: str
    provider: str
    requests: int
    tokens_estimated: int
    tokens_reported: int
    updated_at: str

    @property
    def tokens(self) -> int:
        return self.tokens_estimated + self.tokens_reported


@dataclass(frozen=True, slots=True)
class UsageReservation:
    """A granted (or inspected) budget slot for one real HTTP attempt."""

    date: str
    provider: str
    used: int
    tokens: int
    limit: int
    token_limit: int
    reset_at: str


def usage_date(now: datetime) -> str:
    return _utc(now).date().isoformat()


def usage_reset_at(now: datetime) -> str:
    next_day = _utc(now).date() + timedelta(days=1)
    return (
        datetime.combine(next_day, time.min, tzinfo=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _budget_error(
    *,
    limit: int,
    used: int,
    reset_at: str,
) -> ProviderBudgetExceeded:
    return ProviderBudgetExceeded(
        "provider_budget_exceeded",
        _BUDGET_MESSAGE,
        retryable=False,
        details={
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "resetAt": reset_at,
        },
    )


class ProviderUsageRepository:
    """Atomic daily counters for real provider HTTP attempts.

    ``request_limit``/``token_limit`` of 0 mean "no enforcement, keep counting".
    Every database failure is turned into ``ProviderUsageUnavailable`` so callers
    fail closed; none of the exceptions carries SQL text or row content.
    """

    def __init__(
        self,
        path: Path,
        *,
        request_limit: int = 0,
        token_limit: int = 0,
    ) -> None:
        self._path = path
        self._request_limit = request_limit
        self._token_limit = token_limit

    def precheck_and_reserve(self, provider: SecretKind, now: datetime) -> UsageReservation:
        """Atomically check the budget and count one attempt.

        The ``requests + 1`` bump and the limit decision share one
        ``BEGIN IMMEDIATE`` transaction, so concurrent callers can never pass the
        limit together. A rejected attempt is not counted.
        """

        date = usage_date(now)
        reset_at = usage_reset_at(now)
        updated_at = _iso(now)
        try:
            connection = connect(self._path)
        except sqlite3.Error:
            raise _usage_unavailable() from None
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT requests, tokens_estimated, tokens_reported "
                    "FROM provider_usage WHERE date = ? AND provider = ?",
                    (date, provider),
                ).fetchone()
                used = int(row["requests"]) if row is not None else 0
                tokens = (
                    int(row["tokens_estimated"]) + int(row["tokens_reported"])
                    if row is not None
                    else 0
                )
                if self._request_limit > 0 and used >= self._request_limit:
                    raise _budget_error(limit=self._request_limit, used=used, reset_at=reset_at)
                if self._token_limit > 0 and tokens >= self._token_limit:
                    raise _budget_error(limit=self._token_limit, used=tokens, reset_at=reset_at)
                connection.execute(
                    "INSERT INTO provider_usage "
                    "(date, provider, requests, tokens_estimated, tokens_reported, updated_at) "
                    "VALUES (?, ?, 1, 0, 0, ?) "
                    "ON CONFLICT (date, provider) DO UPDATE SET "
                    "requests = requests + 1, updated_at = excluded.updated_at",
                    (date, provider, updated_at),
                )
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        except sqlite3.Error:
            _rollback_quietly(connection)
            raise _usage_unavailable() from None
        finally:
            connection.close()
        return UsageReservation(
            date=date,
            provider=provider,
            used=used + 1,
            tokens=tokens,
            limit=self._request_limit,
            token_limit=self._token_limit,
            reset_at=reset_at,
        )

    def check_available(self, provider: SecretKind, now: datetime) -> UsageReservation:
        """Read-only precheck used before queueing synchronous work."""

        unenforced = self._request_limit <= 0 and self._token_limit <= 0
        reset_at = usage_reset_at(now)
        if unenforced:
            return UsageReservation(
                date=usage_date(now),
                provider=provider,
                used=0,
                tokens=0,
                limit=0,
                token_limit=0,
                reset_at=reset_at,
            )
        date = usage_date(now)
        try:
            connection = connect(self._path)
            try:
                row = connection.execute(
                    "SELECT requests, tokens_estimated, tokens_reported "
                    "FROM provider_usage WHERE date = ? AND provider = ?",
                    (date, provider),
                ).fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            raise _usage_unavailable() from None
        used = int(row["requests"]) if row is not None else 0
        tokens = (
            int(row["tokens_estimated"]) + int(row["tokens_reported"]) if row is not None else 0
        )
        if self._request_limit > 0 and used >= self._request_limit:
            raise _budget_error(limit=self._request_limit, used=used, reset_at=reset_at)
        if self._token_limit > 0 and tokens >= self._token_limit:
            raise _budget_error(limit=self._token_limit, used=tokens, reset_at=reset_at)
        return UsageReservation(
            date=date,
            provider=provider,
            used=used,
            tokens=tokens,
            limit=self._request_limit,
            token_limit=self._token_limit,
            reset_at=reset_at,
        )

    def add_tokens(
        self,
        provider: SecretKind,
        date: str,
        *,
        reported: int = 0,
        estimated: int = 0,
    ) -> None:
        """Accumulate token counts for a date already reserved by the caller."""

        if reported < 0 or estimated < 0:
            raise ValueError("token counts must be non-negative")
        if reported == 0 and estimated == 0:
            return
        try:
            connection = connect(self._path)
            try:
                connection.execute(
                    "INSERT INTO provider_usage "
                    "(date, provider, requests, tokens_estimated, tokens_reported, updated_at) "
                    "VALUES (?, ?, 0, ?, ?, ?) "
                    "ON CONFLICT (date, provider) DO UPDATE SET "
                    "tokens_estimated = tokens_estimated + excluded.tokens_estimated, "
                    "tokens_reported = tokens_reported + excluded.tokens_reported, "
                    "updated_at = excluded.updated_at",
                    (date, provider, estimated, reported, _iso(datetime.now(UTC))),
                )
            finally:
                connection.close()
        except sqlite3.Error:
            raise _usage_unavailable() from None

    def snapshot(self, date: str) -> list[UsageRow]:
        try:
            connection = connect(self._path)
            try:
                rows = connection.execute(
                    "SELECT date, provider, requests, tokens_estimated, tokens_reported, "
                    "updated_at FROM provider_usage WHERE date = ? ORDER BY provider",
                    (date,),
                ).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            raise _usage_unavailable() from None
        return [
            UsageRow(
                date=str(row["date"]),
                provider=str(row["provider"]),
                requests=int(row["requests"]),
                tokens_estimated=int(row["tokens_estimated"]),
                tokens_reported=int(row["tokens_reported"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]


def _rollback_quietly(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        pass


__all__ = [
    "ProviderUsageRepository",
    "UsageReservation",
    "UsageRow",
    "usage_date",
    "usage_reset_at",
]
