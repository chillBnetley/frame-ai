from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from app.ai.contracts import (
    IssueType,
    RecommendationCategory,
    SceneLabel,
    Severity,
    Text,
    UsageInfo,
)
from app.models.conversion import ConversionMode
from app.models.recipe import (
    MASK_ID_PATTERN,
    EditRecipe,
    StyleId,
)

PHOTOGRAPHER_SCHEMA_VERSION: Literal["stage5/1"] = "stage5/1"
HEURISTIC_CONFIDENCE_NOTE = "启发式置信度，不是校准概率。"
PLANNER_MODE_AUTO: Literal["auto"] = "auto"
PLANNER_MODE_STYLE: Literal["style"] = "style"

EvidenceReference = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
ShortName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
ChangePath = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z][A-Za-z0-9_.\[\]]*$",
    ),
]
MaskId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=MASK_ID_PATTERN),
]
PhotographerStyleId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{1,63}$"),
]

MAX_CHANGES = 10
MAX_NOTES = 8
MAX_DIAGNOSIS_ITEMS = 20
MAX_LOCAL_INTENTS = 8
MAX_FEEDBACK_PATHS = 200
MAX_FEEDBACK_ROWS = 200
MAX_CHANGE_FREQUENCY_ROWS = 20


class _PhotographerModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class PlannerMode(StrEnum):
    AUTO = "auto"
    STYLE = "style"


class StyleCategory(StrEnum):
    SCENE = "scene"
    CREATIVE = "creative"


class DirectionConstraint(StrEnum):
    PRESERVE_SKIN_TONE = "preserve_skin_tone"
    PRESERVE_HIGHLIGHT_DETAIL = "preserve_highlight_detail"
    PRESERVE_SHADOW_DETAIL = "preserve_shadow_detail"
    AVOID_EXTREME_SATURATION = "avoid_extreme_saturation"
    AVOID_EXTREME_CONTRAST = "avoid_extreme_contrast"
    KEEP_AMBIENT_COLOR = "keep_ambient_color"
    NATURAL_LOOK = "natural_look"
    AVOID_COLOR_CAST = "avoid_color_cast"
    MAINTAIN_NEUTRALITY = "maintain_neutrality"
    KEEP_LOW_KEY = "keep_low_key"
    KEEP_WARM_TONES = "keep_warm_tones"


class CreativeChoiceType(StrEnum):
    LOW_KEY_INTENT = "low_key_intent"
    HIGH_KEY_INTENT = "high_key_intent"
    WARM_AMBIENT = "warm_ambient"
    COOL_AMBIENT = "cool_ambient"
    LOW_SATURATION_INTENT = "low_saturation_intent"
    HIGH_SATURATION_INTENT = "high_saturation_intent"
    HIGH_CONTRAST_INTENT = "high_contrast_intent"
    FLAT_LIGHT_INTENT = "flat_light_intent"
    SHALLOW_DEPTH_OF_FIELD = "shallow_depth_of_field"
    ALREADY_EDITED = "already_edited"


class PhotographerPreferences(_PhotographerModel):
    naturalness: float = Field(default=0.7, ge=0.0, le=1.0)
    adjustment_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    allow_stylization: bool = False
    preserve_original_color: bool = True


class StyleEnvelope(_PhotographerModel):
    """Per-parameter magnitude limits used when a style is realized as parameters."""

    exposure_ev: float = Field(default=1.0, ge=0.0, le=5.0)
    contrast: float = Field(default=25.0, ge=0.0, le=100.0)
    highlights: float = Field(default=25.0, ge=0.0, le=100.0)
    shadows: float = Field(default=25.0, ge=0.0, le=100.0)
    whites: float = Field(default=20.0, ge=0.0, le=100.0)
    blacks: float = Field(default=20.0, ge=0.0, le=100.0)
    temperature: float = Field(default=15.0, ge=0.0, le=100.0)
    tint: float = Field(default=10.0, ge=0.0, le=100.0)
    saturation: float = Field(default=15.0, ge=0.0, le=100.0)
    vibrance: float = Field(default=15.0, ge=0.0, le=100.0)
    clarity: float = Field(default=20.0, ge=0.0, le=100.0)
    denoise: float = Field(default=25.0, ge=0.0, le=100.0)
    vignette: float = Field(default=20.0, ge=0.0, le=100.0)
    grain: float = Field(default=15.0, ge=0.0, le=100.0)


class StyleDefinition(_PhotographerModel):
    """A parameterized style. The catalog is independent of the render engine."""

    id: PhotographerStyleId
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+$")] = "1.0"
    name: ShortName
    category: StyleCategory
    description: Text
    supported_scenes: tuple[SceneLabel, ...] = Field(min_length=1, max_length=9)
    default_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    envelope: StyleEnvelope = Field(default_factory=StyleEnvelope)
    constraints: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)
    engine_style: StyleId = "natural"
    enabled: bool = True

    @model_validator(mode="after")
    def _unique_values(self) -> Self:
        if len(set(self.supported_scenes)) != len(self.supported_scenes):
            raise ValueError("supportedScenes must be unique.")
        if len(set(self.constraints)) != len(self.constraints):
            raise ValueError("constraints must be unique.")
        return self


class StyleListResponse(_PhotographerModel):
    styles: tuple[StyleDefinition, ...] = Field(default=(), max_length=32)


class ConversionModeInfo(_PhotographerModel):
    """Public description of what one conversion mode permits and protects."""

    mode: ConversionMode
    name: ShortName
    description: Text
    allowed_adjustments: tuple[str, ...] = Field(min_length=1, max_length=16)
    forbidden_operations: tuple[Text, ...] = Field(min_length=1, max_length=8)
    preservation_constraints: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)
    recommended_strength_min: float = Field(ge=0.0, le=1.0)
    recommended_strength_max: float = Field(ge=0.0, le=1.0)
    recommended_strength_default: float = Field(ge=0.0, le=1.0)
    envelope_scale: float = Field(gt=0.0, le=2.0)

    @model_validator(mode="after")
    def _ranges_and_values_are_consistent(self) -> Self:
        if not (
            self.recommended_strength_min
            <= self.recommended_strength_default
            <= self.recommended_strength_max
        ):
            raise ValueError("recommended strength must satisfy min <= default <= max.")
        if len(set(self.allowed_adjustments)) != len(self.allowed_adjustments):
            raise ValueError("allowedAdjustments must be unique.")
        if len(set(self.forbidden_operations)) != len(self.forbidden_operations):
            raise ValueError("forbiddenOperations must be unique.")
        if len(set(self.preservation_constraints)) != len(self.preservation_constraints):
            raise ValueError("preservationConstraints must be unique.")
        return self


class ConversionModeListResponse(_PhotographerModel):
    modes: tuple[ConversionModeInfo, ...] = Field(min_length=1, max_length=3)


class DiagnosisItem(_PhotographerModel):
    issue_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]
    type: IssueType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_NOTES)


class CreativeChoice(_PhotographerModel):
    type: CreativeChoiceType
    description: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_NOTES)


class DiagnosisResult(_PhotographerModel):
    confirmed: tuple[DiagnosisItem, ...] = Field(default=(), max_length=MAX_DIAGNOSIS_ITEMS)
    possible: tuple[DiagnosisItem, ...] = Field(default=(), max_length=MAX_DIAGNOSIS_ITEMS)
    creative_choices: tuple[CreativeChoice, ...] = Field(default=(), max_length=MAX_NOTES)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_note: str = Field(default=HEURISTIC_CONFIDENCE_NOTE, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _issue_ids_are_unique(self) -> Self:
        ids = [item.issue_id for item in (*self.confirmed, *self.possible)]
        if len(ids) != len(set(ids)):
            raise ValueError("diagnosis issue ids must be unique.")
        return self


class CreativeDirection(_PhotographerModel):
    id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{1,63}$"),
    ]
    name: ShortName
    category: StyleCategory
    description: Text
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    constraints: tuple[DirectionConstraint, ...] = Field(default=(), max_length=11)

    @model_validator(mode="after")
    def _constraints_are_unique(self) -> Self:
        if len(set(self.constraints)) != len(self.constraints):
            raise ValueError("constraints must be unique.")
        return self


class AdjustmentIntent(_PhotographerModel):
    """Untrusted model intent; the generator clamps and rounds these values."""

    exposure_ev: float | None = Field(default=None, allow_inf_nan=False, ge=-5.0, le=5.0)
    contrast: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    highlights: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    shadows: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    whites: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    blacks: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    temperature: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    tint: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    saturation: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    vibrance: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    clarity: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    sharpen: float | None = Field(default=None, allow_inf_nan=False, ge=0.0, le=100.0)
    denoise: float | None = Field(default=None, allow_inf_nan=False, ge=0.0, le=100.0)
    vignette: float | None = Field(default=None, allow_inf_nan=False, ge=-100.0, le=100.0)
    grain: float | None = Field(default=None, allow_inf_nan=False, ge=0.0, le=100.0)


class LocalAdjustmentIntent(_PhotographerModel):
    mask_id: MaskId
    adjustments: AdjustmentIntent

    @model_validator(mode="after")
    def _v1_fields_only(self) -> Self:
        unsupported = [
            name
            for name in ("sharpen", "denoise", "vignette", "grain")
            if getattr(self.adjustments, name) not in (None, 0)
        ]
        if unsupported:
            raise ValueError(
                f"{', '.join(unsupported)} is not supported for local adjustments in v1"
            )
        return self


class PlannerDraft(_PhotographerModel):
    diagnosis: DiagnosisResult
    direction: CreativeDirection
    adjustments: AdjustmentIntent = Field(default_factory=AdjustmentIntent)
    local_adjustments: tuple[LocalAdjustmentIntent, ...] = Field(
        default=(), max_length=MAX_LOCAL_INTENTS
    )
    rationale: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    warnings: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    usage: UsageInfo | None = None

    @model_validator(mode="after")
    def _local_masks_are_unique(self) -> Self:
        mask_ids = [item.mask_id for item in self.local_adjustments]
        if len(mask_ids) != len(set(mask_ids)):
            raise ValueError("local adjustment maskIds must be unique.")
        return self


class PatchDraft(_PhotographerModel):
    supported: bool
    adjustments: AdjustmentIntent | None = None
    local_adjustments: tuple[LocalAdjustmentIntent, ...] = Field(
        default=(), max_length=MAX_LOCAL_INTENTS
    )
    reason: Text
    warnings: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    unsupported: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    usage: UsageInfo | None = None

    @model_validator(mode="after")
    def _unsupported_patch_is_empty(self) -> Self:
        if not self.supported and (self.adjustments is not None or self.local_adjustments):
            raise ValueError("an unsupported patch must not propose changes.")
        return self


class ParameterChange(_PhotographerModel):
    path: ChangePath
    previous: JsonValue = None
    proposed: JsonValue = None
    reason: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_NOTES)


class ProviderInfo(_PhotographerModel):
    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)


class PhotographerPlanResponse(_PhotographerModel):
    schema_version: Literal["stage5/1"] = PHOTOGRAPHER_SCHEMA_VERSION
    plan_id: UUID
    analysis_id: UUID
    session_id: UUID
    image_id: UUID
    base_revision_id: UUID | None = None
    mode: PlannerMode
    is_mock: bool
    degraded: bool = False
    provider: ProviderInfo
    diagnosis: DiagnosisResult
    direction: CreativeDirection
    style_id: PhotographerStyleId | None = None
    style_version: str | None = Field(default=None, min_length=1, max_length=16)
    style_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    conversion_mode: ConversionMode | None = None
    recipe: EditRecipe
    changes: tuple[ParameterChange, ...] = Field(default=(), max_length=MAX_CHANGES)
    warnings: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_note: str = Field(default=HEURISTIC_CONFIDENCE_NOTE, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _change_paths_are_unique(self) -> Self:
        paths = [change.path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("change paths must be unique.")
        return self


class PhotographerPatchResponse(_PhotographerModel):
    schema_version: Literal["stage5/1"] = PHOTOGRAPHER_SCHEMA_VERSION
    patch_id: UUID
    plan_id: UUID
    supported: bool
    recipe: EditRecipe
    changes: tuple[ParameterChange, ...] = Field(default=(), max_length=MAX_CHANGES)
    reason: Text
    warnings: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    unsupported: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)

    @model_validator(mode="after")
    def _change_paths_are_unique(self) -> Self:
        paths = [change.path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("change paths must be unique.")
        return self


class CritiquePoint(_PhotographerModel):
    text: Text
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_NOTES)


class CritiqueTechnical(_PhotographerModel):
    objective: tuple[CritiquePoint, ...] = Field(default=(), max_length=MAX_NOTES)
    possible_issues: tuple[CritiquePoint, ...] = Field(default=(), max_length=MAX_NOTES)


class CritiqueCreative(CritiquePoint):
    subjective: bool = True


class CritiqueSuggestion(_PhotographerModel):
    text: Text
    category: RecommendationCategory
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_NOTES)
    recipe_patch: AdjustmentIntent | None = None


class CritiqueResponse(_PhotographerModel):
    analysis_id: UUID
    is_mock: bool
    generated_by: Literal["deterministic-rules"] = "deterministic-rules"
    strengths: tuple[CritiquePoint, ...] = Field(default=(), max_length=MAX_NOTES)
    technical: CritiqueTechnical = Field(default_factory=CritiqueTechnical)
    creative: tuple[CritiqueCreative, ...] = Field(default=(), max_length=MAX_NOTES)
    suggestions: tuple[CritiqueSuggestion, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)


class CritiqueApplyRequest(_PhotographerModel):
    """Apply one critique suggestion's parameter patch to the session's current recipe."""

    session_id: UUID
    patch: AdjustmentIntent
    preferences: PhotographerPreferences = Field(default_factory=PhotographerPreferences)


class CritiqueApplyResponse(_PhotographerModel):
    """The same validated patch shape the chat flow returns, without a plan anchor."""

    schema_version: Literal["stage5/1"] = PHOTOGRAPHER_SCHEMA_VERSION
    patch_id: UUID
    recipe: EditRecipe
    changes: tuple[ParameterChange, ...] = Field(default=(), max_length=MAX_CHANGES)
    reason: Text
    warnings: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    limitations: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)
    unsupported: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)

    @model_validator(mode="after")
    def _change_paths_are_unique(self) -> Self:
        paths = [change.path for change in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("change paths must be unique.")
        return self


class FeedbackRubric(_PhotographerModel):
    exposure: int | None = Field(default=None, ge=1, le=5)
    color: int | None = Field(default=None, ge=1, le=5)
    skin_tone: int | None = Field(default=None, ge=1, le=5)
    highlights: int | None = Field(default=None, ge=1, le=5)
    shadows: int | None = Field(default=None, ge=1, le=5)
    subject: int | None = Field(default=None, ge=1, le=5)
    local_adjustment: int | None = Field(default=None, ge=1, le=5)
    style: int | None = Field(default=None, ge=1, le=5)
    naturalness: int | None = Field(default=None, ge=1, le=5)
    creative_intent: int | None = Field(default=None, ge=1, le=5)


class FeedbackAction(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"
    RESET = "reset"


class FeedbackSource(StrEnum):
    """Which flow the user was reacting to."""

    PLAN = "plan"
    CHAT = "chat"
    CRITIQUE = "critique"


class FeedbackDimension(StrEnum):
    EXPOSURE = "exposure"
    COLOR = "color"
    SKIN_TONE = "skin_tone"
    HIGHLIGHTS = "highlights"
    SHADOWS = "shadows"
    SUBJECT = "subject"
    LOCAL_ADJUSTMENT = "local_adjustment"
    STYLE = "style"
    NATURALNESS = "naturalness"
    CREATIVE_INTENT = "creative_intent"


class PhotographerFeedbackRequest(_PhotographerModel):
    """One user decision. There is no field for prose: instructions and images stay out."""

    session_id: UUID
    action: FeedbackAction
    source: FeedbackSource | None = None
    plan_id: UUID | None = None
    revision_id: UUID | None = None
    rubric: FeedbackRubric | None = None

    @model_validator(mode="after")
    def _client_actions_are_the_observable_ones(self) -> Self:
        if self.action is FeedbackAction.MODIFIED:
            raise ValueError(
                "modified is derived by comparing the stored recipe; record 'accepted' instead."
            )
        if self.action is FeedbackAction.REJECTED and self.revision_id is not None:
            raise ValueError("revisionId is only accepted with 'accepted' or 'reset'.")
        return self


class PhotographerFeedbackResponse(_PhotographerModel):
    id: UUID
    session_id: UUID
    image_id: UUID
    plan_id: UUID | None = None
    revision_id: UUID | None = None
    source: FeedbackSource | None = None
    action: FeedbackAction
    changed_paths: tuple[ChangePath, ...] = Field(default=(), max_length=MAX_FEEDBACK_PATHS)
    rubric: FeedbackRubric | None = None
    is_mock: bool
    degraded: bool
    created_at: datetime


class FeedbackSourceCounts(_PhotographerModel):
    plan: int
    chat: int
    critique: int
    unset: int


class FeedbackChangeFrequency(_PhotographerModel):
    path: ChangePath
    count: int


class FeedbackDimensionAverage(_PhotographerModel):
    dimension: FeedbackDimension
    average: float = Field(ge=1, le=5)
    count: int = Field(ge=1)


class FeedbackSummary(_PhotographerModel):
    """Counts of what users did. Nothing here may read as a claim of quality improvement."""

    total: int
    accepted: int
    rejected: int
    modified: int
    reset: int
    by_source: FeedbackSourceCounts
    mock_count: int
    real_count: int
    degraded_count: int
    rated_count: int
    change_frequency: tuple[FeedbackChangeFrequency, ...] = Field(
        default=(), max_length=MAX_CHANGE_FREQUENCY_ROWS
    )
    rubric_averages: tuple[FeedbackDimensionAverage, ...] = Field(
        default=(), max_length=len(FeedbackDimension)
    )
    disclaimers: tuple[Text, ...] = Field(default=(), max_length=MAX_NOTES)

    @model_validator(mode="after")
    def _action_counts_add_up(self) -> Self:
        if self.accepted + self.rejected + self.modified + self.reset != self.total:
            raise ValueError("action counts must add up to total.")
        return self


class PhotographerFeedbackListResponse(_PhotographerModel):
    schema_version: Literal["stage5/1"] = PHOTOGRAPHER_SCHEMA_VERSION
    items: tuple[PhotographerFeedbackResponse, ...] = Field(
        default=(), max_length=MAX_FEEDBACK_ROWS
    )
    summary: FeedbackSummary


class PhotographerPlanRequest(_PhotographerModel):
    analysis_id: UUID | None = None
    session_id: UUID
    mode: PlannerMode = PlannerMode.AUTO
    style_id: PhotographerStyleId | None = None
    style_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    conversion_mode: ConversionMode | None = None
    locked_fields: tuple[str, ...] = Field(default=(), max_length=15)
    preferences: PhotographerPreferences = Field(default_factory=PhotographerPreferences)

    @model_validator(mode="after")
    def _style_mode_requires_a_style(self) -> Self:
        if self.mode is PlannerMode.STYLE and self.style_id is None:
            raise ValueError("styleId is required when mode is 'style'.")
        if self.mode is PlannerMode.AUTO and self.style_id is not None:
            raise ValueError("styleId is only accepted when mode is 'style'.")
        if self.mode is PlannerMode.AUTO and self.style_strength is not None:
            raise ValueError("styleStrength is only accepted when mode is 'style'.")
        if self.mode is PlannerMode.AUTO and self.conversion_mode is not None:
            raise ValueError("conversionMode is only accepted when mode is 'style'.")
        allowed = set(AdjustmentIntent.model_fields)
        unknown = sorted(set(self.locked_fields) - allowed)
        if unknown:
            raise ValueError("unknown lockedFields: " + ", ".join(unknown))
        if len(set(self.locked_fields)) != len(self.locked_fields):
            raise ValueError("lockedFields must be unique.")
        return self


class PhotographerPatchRequest(_PhotographerModel):
    plan_id: UUID
    instruction: Text
    preferences: PhotographerPreferences = Field(default_factory=PhotographerPreferences)


class AcceptPlanRequest(_PhotographerModel):
    parent_revision_id: UUID
    render_key: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class PhotographerCritiqueRequest(_PhotographerModel):
    analysis_id: UUID
    preferences: PhotographerPreferences = Field(default_factory=PhotographerPreferences)


_EVIDENCE_REF_PREFIX_ALIASES: tuple[tuple[str, str], ...] = (
    ("measurements.", "measurement."),
    ("report.measurement.", "measurement."),
    ("analysis.measurement.", "measurement."),
)


def canonical_evidence_ref(ref: str) -> str:
    """Normalise the model's common ``measurements.*`` spelling to ``measurement.*``.

    The analysis report is exposed to the planner as a ``measurements`` object,
    but evidence references are defined with the singular prefix. Models
    sometimes mirror the JSON key instead of the documented prefix, which would
    otherwise fail recipe validation and force a deterministic fallback.
    """

    for alias, canonical in _EVIDENCE_REF_PREFIX_ALIASES:
        if ref.startswith(alias):
            return canonical + ref[len(alias) :]
    return ref


def canonical_evidence_refs(refs: object) -> object:
    if not isinstance(refs, list):
        return refs
    return [canonical_evidence_ref(item) if isinstance(item, str) else item for item in refs]


__all__ = [
    "AcceptPlanRequest",
    "AdjustmentIntent",
    "ChangePath",
    "ConversionMode",
    "ConversionModeInfo",
    "ConversionModeListResponse",
    "CreativeChoice",
    "CreativeChoiceType",
    "CreativeDirection",
    "CritiqueApplyRequest",
    "CritiqueApplyResponse",
    "CritiqueCreative",
    "CritiquePoint",
    "CritiqueResponse",
    "CritiqueSuggestion",
    "CritiqueTechnical",
    "DiagnosisItem",
    "DiagnosisResult",
    "DirectionConstraint",
    "EvidenceReference",
    "FeedbackAction",
    "FeedbackChangeFrequency",
    "FeedbackDimension",
    "FeedbackDimensionAverage",
    "FeedbackRubric",
    "FeedbackSource",
    "FeedbackSourceCounts",
    "FeedbackSummary",
    "HEURISTIC_CONFIDENCE_NOTE",
    "LocalAdjustmentIntent",
    "MAX_CHANGE_FREQUENCY_ROWS",
    "MAX_CHANGES",
    "MAX_FEEDBACK_PATHS",
    "MAX_FEEDBACK_ROWS",
    "ParameterChange",
    "PatchDraft",
    "PHOTOGRAPHER_SCHEMA_VERSION",
    "PhotographerCritiqueRequest",
    "PhotographerFeedbackListResponse",
    "PhotographerFeedbackRequest",
    "PhotographerFeedbackResponse",
    "PhotographerPatchRequest",
    "PhotographerPatchResponse",
    "PhotographerPlanRequest",
    "PhotographerPlanResponse",
    "PhotographerPreferences",
    "PhotographerStyleId",
    "PlannerDraft",
    "PlannerMode",
    "ProviderInfo",
    "StyleCategory",
    "StyleDefinition",
    "StyleEnvelope",
    "StyleListResponse",
    "canonical_evidence_ref",
    "canonical_evidence_refs",
]
