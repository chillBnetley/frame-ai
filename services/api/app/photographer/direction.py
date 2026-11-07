from __future__ import annotations

from app.ai.contracts import IssueType
from app.models.analysis_report import AnalysisReport
from app.models.photographer import (
    CreativeDirection,
    DiagnosisResult,
    DirectionConstraint,
    PhotographerPreferences,
    StyleDefinition,
)
from app.photographer.rules import (
    clamp,
    is_balanced_frame,
    is_cool_ambient,
    is_high_saturation,
    is_low_key,
    is_low_saturation,
    is_strong_color_cast,
    is_warm_ambient,
    round2,
)
from app.photographer.styles import direction_for_scene

_DIRECTION_CONSTRAINT_LIMIT = 11
_UNDEREXPOSURE_TYPES = frozenset({IssueType.UNDEREXPOSURE, IssueType.SUBJECT_UNDEREXPOSURE})
_COLOR_BIAS_TYPES = frozenset({IssueType.COLOR_CAST, IssueType.TEMPERATURE_MISMATCH})
_HIGHLIGHT_TYPES = frozenset(
    {IssueType.HIGHLIGHT_CLIPPING, IssueType.BACKGROUND_OVEREXPOSURE, IssueType.OVEREXPOSURE}
)
_SHADOW_TYPES = frozenset({IssueType.SHADOW_CLIPPING})


def determine_direction(
    report: AnalysisReport,
    diagnosis: DiagnosisResult,
    preferences: PhotographerPreferences,
    style: StyleDefinition | None = None,
    *,
    style_strength: float | None = None,
) -> CreativeDirection:
    """Combine the scene/style baseline with constraints implied by the diagnosis."""
    base = direction_for_scene(
        report.scene.primary,
        preferences,
        style,
        style_strength=style_strength,
    )
    constraint_names = (*base.constraints, *_context_constraints(report, diagnosis))
    constraints = tuple(dict.fromkeys(constraint_names))[:_DIRECTION_CONSTRAINT_LIMIT]
    return CreativeDirection(
        id=base.id,
        name=base.name,
        category=base.category,
        description=base.description,
        strength=_resolve_strength(base.strength, report, diagnosis, style),
        constraints=constraints,
    )


def _context_constraints(
    report: AnalysisReport,
    diagnosis: DiagnosisResult,
) -> tuple[DirectionConstraint, ...]:
    confirmed = {item.type for item in diagnosis.confirmed}
    constraints: list[DirectionConstraint] = []

    if is_low_key(report) and not confirmed & _UNDEREXPOSURE_TYPES:
        constraints.append(DirectionConstraint.KEEP_LOW_KEY)

    if not confirmed & _COLOR_BIAS_TYPES:
        if is_warm_ambient(report) or is_cool_ambient(report):
            constraints.append(DirectionConstraint.KEEP_AMBIENT_COLOR)
        if is_warm_ambient(report):
            constraints.append(DirectionConstraint.KEEP_WARM_TONES)

    if is_high_saturation(report) and IssueType.SATURATION_ISSUE not in confirmed:
        constraints.append(DirectionConstraint.AVOID_EXTREME_SATURATION)
    if is_low_saturation(report) and IssueType.SATURATION_ISSUE not in confirmed:
        constraints.append(DirectionConstraint.NATURAL_LOOK)

    if is_strong_color_cast(report):
        constraints.append(DirectionConstraint.AVOID_COLOR_CAST)
    if confirmed & _HIGHLIGHT_TYPES:
        constraints.append(DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL)
    if confirmed & _SHADOW_TYPES:
        constraints.append(DirectionConstraint.PRESERVE_SHADOW_DETAIL)

    if is_balanced_frame(report) and not report.issues:
        constraints.append(DirectionConstraint.NATURAL_LOOK)

    return tuple(constraints)


def _resolve_strength(
    base_strength: float,
    report: AnalysisReport,
    diagnosis: DiagnosisResult,
    style: StyleDefinition | None,
) -> float:
    if style is not None:
        return base_strength

    strength = base_strength
    if not diagnosis.confirmed and not diagnosis.possible:
        strength = min(strength, 0.35)
    if is_low_key(report) and not any(
        item.type in _UNDEREXPOSURE_TYPES for item in diagnosis.confirmed
    ):
        strength = min(strength, 0.3)
    if is_balanced_frame(report) and not report.issues:
        strength = min(strength, 0.3)
    return round2(clamp(strength, 0.0, 1.0))


__all__ = ["determine_direction"]
