from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.ai.contracts import (
    AnalysisOptions,
    DecisionResult,
    IssueCandidate,
    MeasurementSummary,
    SceneLabel,
    VisionResult,
)
from app.models.analysis_report import AnalysisReport
from app.models.personal_style import PersonalStyleProfile
from app.models.photographer import (
    CreativeDirection,
    PatchDraft,
    PhotographerPreferences,
    PlannerDraft,
    PlannerMode,
    StyleDefinition,
)
from app.models.recipe import EditRecipe
from app.models.style_authoring import StyleAuthoringDraft

if TYPE_CHECKING:
    from app.ai.style_context import StyleGenerationContext


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


@dataclass(frozen=True, slots=True)
class PlannerRequest:
    analysis: AnalysisReport
    recipe: EditRecipe
    preferences: PhotographerPreferences
    mode: PlannerMode = PlannerMode.AUTO
    style: StyleDefinition | None = None
    style_strength: float | None = None
    style_context: StyleGenerationContext | None = None


@dataclass(frozen=True, slots=True)
class PatchRequest:
    analysis: AnalysisReport
    recipe: EditRecipe
    instruction: str
    preferences: PhotographerPreferences
    direction: CreativeDirection | None = None


@dataclass(frozen=True, slots=True)
class StyleAuthoringRequest:
    """Natural-language style creation or refinement request."""

    name: str
    description: str
    avoid_text: str | None = None
    suitable_scenes: tuple[SceneLabel, ...] = ()
    base_profile: PersonalStyleProfile | None = None
    instruction: str | None = None


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


class PhotographyPlannerProvider(Protocol):
    name: str
    model: str
    is_mock: bool
    prompt_version: str

    def plan(self, request: PlannerRequest) -> PlannerDraft:
        """Return a structured planning draft; never perform pixel operations."""
        ...

    def adjust(self, request: PatchRequest) -> PatchDraft:
        """Return a minimal structured patch draft for a natural-language instruction."""
        ...

    def author_style(self, request: StyleAuthoringRequest) -> StyleAuthoringDraft:
        """Parse or refine a structured personal style without executing it."""
        ...

    def check_connection(self, *, timeout: float | None = None) -> int:
        """Return latency in milliseconds after a text-only connectivity check."""
        ...
