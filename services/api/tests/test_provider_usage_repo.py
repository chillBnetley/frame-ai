from __future__ import annotations

import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai.errors import ProviderBudgetExceeded, ProviderUsageUnavailable
from app.repositories.db import initialize_database
from app.repositories.provider_usage_repo import (
    ProviderUsageRepository,
    usage_date,
    usage_reset_at,
)

NOW = datetime(2026, 11, 8, 12, 30, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "frame.db"
    initialize_database(path)
    return path


def repository(database: Path, *, requests: int = 0, tokens: int = 0) -> ProviderUsageRepository:
    return ProviderUsageRepository(
        database,
        request_limit=requests,
        token_limit=tokens,
    )


def test_reservation_counts_one_request_and_tokens_accumulate(database: Path):
    repo = repository(database)

    reservation = repo.precheck_and_reserve("vision", NOW)
    repo.add_tokens("vision", reservation.date, reported=41)

    [row] = repo.snapshot(usage_date(NOW))
    assert row.provider == "vision"
    assert row.requests == 1
    assert row.tokens_reported == 41
    assert row.tokens_estimated == 0
    assert reservation.used == 1


def test_estimated_tokens_accumulate_without_reported(database: Path):
    repo = repository(database)
    reservation = repo.precheck_and_reserve("decision", NOW)

    repo.add_tokens("decision", reservation.date, estimated=17)
    repo.add_tokens("decision", reservation.date, estimated=3)

    [row] = repo.snapshot(usage_date(NOW))
    assert row.tokens_estimated == 20
    assert row.tokens_reported == 0


def test_request_limit_rejects_the_next_attempt_without_counting_it(database: Path):
    repo = repository(database, requests=1)
    repo.precheck_and_reserve("vision", NOW)

    with pytest.raises(ProviderBudgetExceeded) as error:
        repo.precheck_and_reserve("vision", NOW)

    assert error.value.code == "provider_budget_exceeded"
    assert error.value.retryable is False
    assert error.value.details == {
        "limit": 1,
        "used": 1,
        "remaining": 0,
        "resetAt": "2026-11-09T00:00:00Z",
    }
    [row] = repo.snapshot(usage_date(NOW))
    assert row.requests == 1


def test_token_limit_blocks_a_new_attempt_once_reached(database: Path):
    repo = repository(database, tokens=100)
    reservation = repo.precheck_and_reserve("planner", NOW)
    repo.add_tokens("planner", reservation.date, reported=100)

    with pytest.raises(ProviderBudgetExceeded) as error:
        repo.precheck_and_reserve("planner", NOW)

    assert error.value.details == {
        "limit": 100,
        "used": 100,
        "remaining": 0,
        "resetAt": "2026-11-09T00:00:00Z",
    }
    [row] = repo.snapshot(usage_date(NOW))
    assert row.requests == 1


def test_a_new_utc_day_starts_from_zero(database: Path):
    repo = repository(database, requests=1)
    first = repo.precheck_and_reserve("vision", NOW)
    repo.add_tokens("vision", first.date, reported=9)

    next_day = datetime(2026, 11, 9, 0, 0, 1, tzinfo=UTC)
    second = repo.precheck_and_reserve("vision", next_day)

    assert second.date == "2026-11-09"
    [yesterday] = repo.snapshot("2026-11-08")
    [today] = repo.snapshot("2026-11-09")
    assert yesterday.requests == 1
    assert yesterday.tokens_reported == 9
    assert today.requests == 1
    assert today.tokens_reported == 0


def test_concurrent_reservations_allow_exactly_the_limit(database: Path):
    repo = repository(database, requests=3)
    barrier = threading.Barrier(8)
    granted: list[str] = []
    rejected: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        barrier.wait()
        try:
            reservation = repo.precheck_and_reserve("vision", NOW)
        except ProviderBudgetExceeded:
            with lock:
                rejected.append("budget")
        else:
            with lock:
                granted.append(reservation.date)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(granted) == 3
    assert len(rejected) == 5
    [row] = repo.snapshot(usage_date(NOW))
    assert row.requests == 3


def test_read_only_check_does_not_count_an_attempt(database: Path):
    repo = repository(database, requests=1)

    repo.check_available("vision", NOW)
    repo.check_available("vision", NOW)

    assert repo.snapshot(usage_date(NOW)) == []
    repo.precheck_and_reserve("vision", NOW)
    with pytest.raises(ProviderBudgetExceeded):
        repo.check_available("vision", NOW)


def test_zero_limits_skip_the_read_only_check(database: Path):
    repo = repository(database)

    reservation = repo.check_available("decision", NOW)

    assert reservation.limit == 0
    assert repo.snapshot(usage_date(NOW)) == []


def test_database_failure_fails_closed_without_leaking_the_path(tmp_path: Path):
    broken = tmp_path / "not-a-database"
    broken.mkdir()
    repo = ProviderUsageRepository(broken, request_limit=1)

    with pytest.raises(ProviderUsageUnavailable) as error:
        repo.precheck_and_reserve("vision", NOW)

    assert error.value.code == "provider_usage_unavailable"
    assert error.value.retryable is False
    assert str(broken) not in str(error.value)
    assert str(broken) not in error.value.message


def test_corrupt_database_fails_closed(tmp_path: Path):
    corrupt = tmp_path / "frame.db"
    corrupt.write_bytes(b"this is not a sqlite database")
    repo = ProviderUsageRepository(corrupt)

    with pytest.raises(ProviderUsageUnavailable):
        repo.precheck_and_reserve("vision", NOW)
    with pytest.raises(ProviderUsageUnavailable):
        repo.snapshot(usage_date(NOW))


@pytest.mark.parametrize(
    "module",
    [
        "app.repositories.provider_usage_repo",
        "app.services.usage_meter",
        "app.ai.providers.openai_compatible",
        "app.ai.factory",
    ],
)
def test_fresh_interpreter_can_import_the_usage_modules(module: str):
    api_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-c", f"import {module}; print('ok')"],
        cwd=api_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_snapshot_and_reset_helpers_use_utc():
    assert usage_date(NOW) == "2026-11-08"
    assert usage_reset_at(NOW) == "2026-11-09T00:00:00Z"
