from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.export_admission import AdmissionSnapshot, ExportAdmission


def test_admission_requires_at_least_one_slot():
    with pytest.raises(ValueError):
        ExportAdmission(max_concurrency=0, max_total_mb=1000)


def test_concurrency_cap_blocks_the_next_job_even_with_memory_to_spare():
    admission = ExportAdmission(max_concurrency=2, max_total_mb=10_000)

    assert admission.try_acquire(100.0)
    assert admission.try_acquire(100.0)
    assert admission.try_acquire(100.0) is False

    admission.release(100.0)
    assert admission.try_acquire(100.0)
    assert admission.snapshot() == AdmissionSnapshot(
        active=2, reserved_mb=200.0, max_concurrency=2, max_total_mb=10_000
    )


def test_memory_budget_blocks_a_job_that_would_not_fit_alongside_active_ones():
    admission = ExportAdmission(max_concurrency=4, max_total_mb=1_000)

    assert admission.try_acquire(600.0)
    assert admission.try_acquire(350.0)
    assert admission.snapshot().reserved_mb == pytest.approx(950.0)

    # One slot is still free, but the summed estimate would cross the budget.
    assert admission.try_acquire(60.0) is False
    assert admission.snapshot().active == 2

    admission.release(350.0)
    assert admission.try_acquire(60.0)
    assert admission.snapshot().active == 2


def test_release_returns_the_reserved_estimate_to_the_pool():
    admission = ExportAdmission(max_concurrency=1, max_total_mb=500)

    assert admission.try_acquire(500.0)
    assert admission.try_acquire(1.0) is False
    admission.release(500.0)

    assert admission.snapshot() == AdmissionSnapshot(
        active=0, reserved_mb=0.0, max_concurrency=1, max_total_mb=500
    )


def test_releasing_a_reservation_that_was_never_made_is_an_error():
    admission = ExportAdmission(max_concurrency=1, max_total_mb=500)

    with pytest.raises(ValueError):
        admission.release(10.0)


def test_negative_reserve_is_rejected():
    with pytest.raises(ValueError):
        ExportAdmission(max_concurrency=1, max_total_mb=500, reserve_mb=-1)


def test_real_available_memory_gate_blocks_a_job_that_would_eat_the_reserve():
    admission = ExportAdmission(
        max_concurrency=2,
        max_total_mb=10_000,
        reserve_mb=256,
        available_mb=lambda: 1_200.0,
    )

    assert admission.try_acquire(944.0)
    assert admission.try_acquire(945.0) is False
    assert admission.snapshot().active == 1


def test_real_available_memory_gate_allows_the_exact_reserve_boundary():
    admission = ExportAdmission(
        max_concurrency=1,
        max_total_mb=10_000,
        reserve_mb=256,
        available_mb=lambda: 1_256.0,
    )

    assert admission.try_acquire(1_000.0)
    admission.release(1_000.0)
    assert admission.try_acquire(1_000.5) is False


def test_zero_reserve_does_not_probe_real_memory():
    calls: list[None] = []

    def probe() -> float:
        calls.append(None)
        return 0.0

    admission = ExportAdmission(
        max_concurrency=1,
        max_total_mb=500,
        reserve_mb=0,
        available_mb=probe,
    )

    assert admission.try_acquire(500.0)
    assert calls == []


def test_threads_racing_for_slots_never_exceed_the_cap_or_the_budget():
    admission = ExportAdmission(max_concurrency=3, max_total_mb=1_000)
    start = threading.Barrier(8, timeout=10)
    granted: list[str] = []
    lock = threading.Lock()

    def contend(worker_id: int) -> bool:
        start.wait()
        if not admission.try_acquire(300.0):
            return False
        with lock:
            granted.append(str(worker_id))
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(contend, range(8)))

    assert sum(results) == 3
    assert len(granted) == 3
    assert admission.snapshot().active == 3
    assert admission.snapshot().reserved_mb == pytest.approx(900.0)
