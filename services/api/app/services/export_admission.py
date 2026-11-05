from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import psutil  # type: ignore[import-untyped]

_MIB = 1024 * 1024


@dataclass(frozen=True)
class AdmissionSnapshot:
    active: int
    reserved_mb: float
    max_concurrency: int
    max_total_mb: float


class ExportAdmission:
    """Concurrency and memory gate for export jobs.

    Exports render at full canvas and cannot be interrupted, so a job that
    does not fit alongside the ones already running is rejected right away
    instead of waiting for a slot.

    The static budget is an estimate; ``reserve_mb`` adds a second gate on
    the memory the machine actually has free, so a box that is already busy
    with something else does not accept an export it cannot finish.
    """

    def __init__(
        self,
        *,
        max_concurrency: int,
        max_total_mb: float,
        reserve_mb: float = 0.0,
        available_mb: Callable[[], float] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if reserve_mb < 0:
            raise ValueError("reserve_mb must not be negative")
        self.max_concurrency = max_concurrency
        self.max_total_mb = max_total_mb
        self.reserve_mb = reserve_mb
        self._available_mb = available_mb
        self._active: list[float] = []
        self._lock = threading.Lock()

    def _available(self) -> float:
        if self._available_mb is not None:
            return float(self._available_mb())
        return float(psutil.virtual_memory().available / _MIB)

    def try_acquire(self, estimate_mb: float) -> bool:
        with self._lock:
            if len(self._active) >= self.max_concurrency:
                return False
            if sum(self._active) + estimate_mb > self.max_total_mb:
                return False
            if self.reserve_mb and self._available() - estimate_mb < self.reserve_mb:
                return False
            self._active.append(estimate_mb)
            return True

    def release(self, estimate_mb: float) -> None:
        with self._lock:
            self._active.remove(estimate_mb)

    def snapshot(self) -> AdmissionSnapshot:
        with self._lock:
            return AdmissionSnapshot(
                active=len(self._active),
                reserved_mb=float(sum(self._active)),
                max_concurrency=self.max_concurrency,
                max_total_mb=self.max_total_mb,
            )
