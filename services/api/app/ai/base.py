from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ai.contracts import (
    AnalysisOptions,
    DecisionResult,
    IssueCandidate,
    MeasurementSummary,
    VisionResult,
)


@dataclass(frozen=True, slots=True)
class ModelImage:
    data: bytes
    mime_type: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class VisionRequest:
    image: ModelImage
    options: AnalysisOptions
    measurements: MeasurementSummary


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    vision: VisionResult
    measurements: MeasurementSummary
    candidates: tuple[IssueCandidate, ...]
    options: AnalysisOptions


class VisionProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def analyze(self, request: VisionRequest) -> VisionResult:
        """Return semantic scene, subject, lighting, color, and composition data."""
        ...

    def check_connection(self, *, timeout: float | None = None) -> int:
        """Return latency in milliseconds after a text-only connectivity check."""
        ...


class PhotographyDecisionProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def diagnose(self, request: DecisionRequest) -> DecisionResult:
        """Select grounded issues and produce actionable recommendations."""
        ...

    def check_connection(self, *, timeout: float | None = None) -> int:
        """Return latency in milliseconds after a text-only connectivity check."""
        ...
