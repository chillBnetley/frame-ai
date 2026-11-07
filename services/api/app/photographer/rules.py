from __future__ import annotations

from app.ai.contracts import (
    ColorTemperature,
    ContrastLevel,
    IssueType,
    SaturationLevel,
)
from app.models.analysis_report import AnalysisReport, IssueReport
from app.models.photographer import (
    AdjustmentIntent,
    CreativeChoice,
    CreativeChoiceType,
    PhotographerPreferences,
    StyleDefinition,
)
from app.models.recipe import EditRecipe

COLOR_CAST_THRESHOLD = 0.08

_CONFLICTING_ISSUE_SETS: tuple[frozenset[IssueType], ...] = (
    frozenset({IssueType.UNDEREXPOSURE, IssueType.OVEREXPOSURE}),
    frozenset({IssueType.FLAT_LIGHTING, IssueType.HARSH_CONTRAST}),
)

_MEASUREMENT_REFS: dict[IssueType, tuple[str, ...]] = {
    IssueType.OVEREXPOSURE: ("measurement.luminance.p50", "measurement.clipping.highlightsPct"),
    IssueType.UNDEREXPOSURE: ("measurement.luminance.p50", "measurement.clipping.shadowsPct"),
    IssueType.HIGHLIGHT_CLIPPING: ("measurement.clipping.highlightsPct",),
    IssueType.SHADOW_CLIPPING: ("measurement.clipping.shadowsPct",),
    IssueType.SUBJECT_UNDEREXPOSURE: ("measurement.luminance.p50",),
    IssueType.BACKGROUND_OVEREXPOSURE: ("measurement.clipping.highlightsPct",),
    IssueType.COLOR_CAST: ("measurement.color.cast.temperature", "measurement.color.cast.tint"),
    IssueType.TEMPERATURE_MISMATCH: ("measurement.color.cast.temperature",),
    IssueType.SATURATION_ISSUE: ("measurement.color.saturationMean",),
    IssueType.COLOR_HIERARCHY_ISSUE: ("measurement.color.colorConcentration",),
    IssueType.SUBJECT_PLACEMENT: ("composition.subjectPosition",),
    IssueType.BALANCE_ISSUE: ("composition.balance",),
    IssueType.NEGATIVE_SPACE_ISSUE: ("composition.negativeSpace",),
    IssueType.HORIZON_TILT: ("measurement.composition.horizonTiltDeg",),
    IssueType.FOCUS_ISSUE: ("measurement.detail.sharpness",),
    IssueType.MOTION_BLUR: ("measurement.detail.sharpness",),
    IssueType.HIGH_NOISE: ("measurement.detail.noiseEstimate",),
    IssueType.LOW_DETAIL: ("measurement.detail.sharpness",),
    IssueType.HARSH_CONTRAST: ("measurement.luminance.std", "lighting.contrast"),
    IssueType.FLAT_LIGHTING: ("lighting.contrast", "measurement.luminance.std"),
}

_SCENE_BIAS: dict[str, dict[str, float]] = {
    "portrait": {"vibrance": 4.0},
    "landscape": {"vibrance": 8.0, "clarity": 6.0, "highlights": -6.0},
    "street": {"contrast": 5.0, "clarity": 5.0},
    "architecture": {"clarity": 7.0, "highlights": -6.0},
    "night": {"denoise": 12.0, "shadows": 8.0},
    "indoor": {},
    "food": {"saturation": 4.0, "vibrance": 4.0},
    "nature": {"vibrance": 7.0},
    "other": {},
}

_ISSUE_BIAS: dict[IssueType, dict[str, float]] = {
    IssueType.OVEREXPOSURE: {"exposureEv": -0.4, "highlights": -10.0, "whites": -8.0},
    IssueType.UNDEREXPOSURE: {"exposureEv": 0.4, "shadows": 8.0},
    IssueType.HIGHLIGHT_CLIPPING: {"highlights": -28.0, "whites": -12.0},
    IssueType.SHADOW_CLIPPING: {"shadows": 28.0, "blacks": 6.0},
    IssueType.SUBJECT_UNDEREXPOSURE: {"exposureEv": 0.15, "shadows": 12.0},
    IssueType.BACKGROUND_OVEREXPOSURE: {"highlights": -22.0, "whites": -8.0},
    IssueType.COLOR_CAST: {},
    IssueType.TEMPERATURE_MISMATCH: {},
    IssueType.SATURATION_ISSUE: {},
    IssueType.COLOR_HIERARCHY_ISSUE: {"vibrance": 5.0},
    IssueType.FOCUS_ISSUE: {"sharpen": 18.0, "clarity": 8.0},
    IssueType.MOTION_BLUR: {"sharpen": 15.0},
    IssueType.HIGH_NOISE: {"denoise": 22.0},
    IssueType.LOW_DETAIL: {"sharpen": 15.0, "clarity": 8.0},
    IssueType.HARSH_CONTRAST: {"contrast": -12.0, "highlights": -8.0, "shadows": 8.0},
    IssueType.FLAT_LIGHTING: {"contrast": 10.0, "clarity": 6.0},
}

_STYLE_COLOR_FIELDS = frozenset(
    {"temperature", "tint", "saturation", "vibrance", "contrast", "clarity"}
)
_B100_FIELDS = frozenset(
    {
        "contrast",
        "highlights",
        "shadows",
        "whites",
        "blacks",
        "temperature",
        "tint",
        "saturation",
        "vibrance",
        "clarity",
        "vignette",
    }
)
_U100_FIELDS = frozenset({"sharpen", "denoise", "grain"})


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def round2(value: float) -> float:
    return round(value + 0.0, 2)


def available_mask_ids(recipe: EditRecipe) -> frozenset[str]:
    return frozenset({"full", *(mask.id for mask in recipe.masks)})


def is_low_key(report: AnalysisReport) -> bool:
    return report.measurements.luminance.p50 <= 0.24


def is_high_key(report: AnalysisReport) -> bool:
    return report.measurements.luminance.p50 >= 0.72


def is_high_saturation(report: AnalysisReport) -> bool:
    return (
        report.color.saturation is SaturationLevel.HIGH
        or report.measurements.color.saturation_mean >= 0.55
    )


def is_low_saturation(report: AnalysisReport) -> bool:
    return (
        report.color.saturation is SaturationLevel.LOW
        or report.measurements.color.saturation_mean <= 0.18
    )


def is_warm_ambient(report: AnalysisReport) -> bool:
    return report.color.temperature is ColorTemperature.WARM


def is_cool_ambient(report: AnalysisReport) -> bool:
    return report.color.temperature is ColorTemperature.COOL


def is_high_contrast(report: AnalysisReport) -> bool:
    return (
        report.lighting.contrast is ContrastLevel.HIGH or report.measurements.luminance.std >= 0.28
    )


def is_flat_lighting(report: AnalysisReport) -> bool:
    return (
        report.lighting.contrast is ContrastLevel.LOW and report.measurements.luminance.std <= 0.16
    )


def is_strong_color_cast(report: AnalysisReport) -> bool:
    cast = report.measurements.color.cast
    return abs(cast.temperature) >= COLOR_CAST_THRESHOLD or abs(cast.tint) >= COLOR_CAST_THRESHOLD


def is_balanced_frame(report: AnalysisReport) -> bool:
    luminance = report.measurements.luminance
    clipping = report.measurements.clipping
    color = report.measurements.color
    detail = report.measurements.detail
    cast = color.cast
    return (
        0.32 <= luminance.p50 <= 0.68
        and luminance.p1 >= 0.01
        and luminance.p99 <= 0.99
        and clipping.highlights_pct <= 3.0
        and clipping.shadows_pct <= 3.0
        and 0.18 <= color.saturation_mean <= 0.6
        and abs(cast.temperature) <= COLOR_CAST_THRESHOLD
        and abs(cast.tint) <= COLOR_CAST_THRESHOLD
        and detail.sharpness >= 0.12
        and detail.noise_estimate <= 0.35
    )


def has_conflicting_issues(report: AnalysisReport) -> bool:
    issue_types = {issue.type for issue in report.issues}
    return any(group <= issue_types for group in _CONFLICTING_ISSUE_SETS)


def is_creative_sensitive_issue(issue: IssueReport, report: AnalysisReport) -> bool:
    """Return True when an apparent defect may be an intentional creative choice."""
    if issue.type in {IssueType.UNDEREXPOSURE, IssueType.SUBJECT_UNDEREXPOSURE}:
        return is_low_key(report)
    if issue.type is IssueType.SATURATION_ISSUE:
        return is_low_saturation(report) or is_high_saturation(report)
    if issue.type is IssueType.HARSH_CONTRAST:
        return is_high_contrast(report)
    if issue.type is IssueType.TEMPERATURE_MISMATCH:
        return (is_warm_ambient(report) or is_cool_ambient(report)) and not is_strong_color_cast(
            report
        )
    if issue.type is IssueType.COLOR_CAST:
        return not is_strong_color_cast(report)
    if issue.type is IssueType.FLAT_LIGHTING:
        return is_flat_lighting(report)
    return False


def creative_choices(report: AnalysisReport) -> tuple[CreativeChoice, ...]:
    choices: list[CreativeChoice] = []

    if is_low_key(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.LOW_KEY_INTENT,
                description="整体低调，可能是刻意保留的暗调氛围。",
                evidence_refs=("measurement.luminance.p50",),
            )
        )
    if is_high_key(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.HIGH_KEY_INTENT,
                description="整体明亮通透，可能是高调风格的创作选择。",
                evidence_refs=("measurement.luminance.p50",),
            )
        )
    cast_is_deliberate = not is_strong_color_cast(report)
    if is_warm_ambient(report) and cast_is_deliberate:
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.WARM_AMBIENT,
                description="画面偏暖，可能是现场氛围或刻意的暖调风格。",
                evidence_refs=("color.temperature",),
            )
        )
    if is_cool_ambient(report) and cast_is_deliberate:
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.COOL_AMBIENT,
                description="画面偏冷，可能是现场氛围或刻意的冷调风格。",
                evidence_refs=("color.temperature",),
            )
        )
    if is_low_saturation(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.LOW_SATURATION_INTENT,
                description="色彩强度较低，可能是刻意降低饱和度的创作选择。",
                evidence_refs=("measurement.color.saturationMean",),
            )
        )
    if is_high_saturation(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.HIGH_SATURATION_INTENT,
                description="色彩强度较高，可能是刻意的鲜明色彩风格。",
                evidence_refs=("measurement.color.saturationMean",),
            )
        )
    if is_high_contrast(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.HIGH_CONTRAST_INTENT,
                description="明暗反差较强，可能是刻意强调光影的选择。",
                evidence_refs=("measurement.luminance.std",),
            )
        )
    if is_flat_lighting(report):
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.FLAT_LIGHT_INTENT,
                description="光线较平，可能是柔和自然光的现场条件。",
                evidence_refs=("lighting.contrast",),
            )
        )
    if is_balanced_frame(report) and not report.issues:
        choices.append(
            CreativeChoice(
                type=CreativeChoiceType.ALREADY_EDITED,
                description="画面曝光、色彩与细节已较平衡，可能不需要进一步调整。",
                evidence_refs=(
                    "measurement.luminance.p50",
                    "measurement.color.saturationMean",
                    "measurement.clipping.highlightsPct",
                ),
            )
        )
    return tuple(choices)


def evidence_refs_for_issue(issue: IssueReport) -> tuple[str, ...]:
    refs = [issue.id, *issue.region_ids, *_MEASUREMENT_REFS.get(issue.type, ())]
    return tuple(dict.fromkeys(refs))[:8]


def suggest_adjustments(
    report: AnalysisReport,
    preferences: PhotographerPreferences,
    style: StyleDefinition | None = None,
) -> AdjustmentIntent:
    values: dict[str, float] = {}

    def add(field: str, delta: float) -> None:
        values[field] = values.get(field, 0.0) + delta

    for field, delta in _SCENE_BIAS[report.scene.primary.value].items():
        add(field, delta)

    issue_types = {issue.type for issue in report.issues}
    for issue in report.issues:
        if issue.type is IssueType.HARSH_CONTRAST and is_high_contrast(report):
            continue
        for field, delta in _ISSUE_BIAS.get(issue.type, {}).items():
            add(field, delta)

    strong_cast = is_strong_color_cast(report)
    if IssueType.COLOR_CAST in issue_types and strong_cast:
        cast = report.measurements.color.cast
        add("temperature", clamp(-cast.temperature * 400.0, -20.0, 20.0))
        add("tint", clamp(-cast.tint * 300.0, -15.0, 15.0))
    elif IssueType.TEMPERATURE_MISMATCH in issue_types and strong_cast:
        if is_warm_ambient(report):
            add("temperature", -6.0)
        elif is_cool_ambient(report):
            add("temperature", 6.0)

    if IssueType.SATURATION_ISSUE in issue_types and is_high_saturation(report):
        add("saturation", -10.0)
        add("vibrance", -5.0)

    _protect_creative_choices(report, values)
    return apply_preferences_and_style(values, preferences, style)


def issue_adjustments(
    report: AnalysisReport,
    issue_type: IssueType,
    preferences: PhotographerPreferences,
) -> AdjustmentIntent:
    """The parameter deltas one reported issue justifies, with creative protection.

    Per-issue rather than aggregate: a critique suggestion has to stand on its own
    when the user applies only that one suggestion.
    """
    values = dict(_ISSUE_BIAS.get(issue_type, {}))
    strong_cast = is_strong_color_cast(report)

    if issue_type is IssueType.COLOR_CAST and strong_cast:
        cast = report.measurements.color.cast
        values["temperature"] = clamp(-cast.temperature * 400.0, -20.0, 20.0)
        values["tint"] = clamp(-cast.tint * 300.0, -15.0, 15.0)
    elif issue_type is IssueType.TEMPERATURE_MISMATCH and strong_cast:
        if is_warm_ambient(report):
            values["temperature"] = -6.0
        elif is_cool_ambient(report):
            values["temperature"] = 6.0

    if issue_type is IssueType.SATURATION_ISSUE and is_high_saturation(report):
        values["saturation"] = -10.0
        values["vibrance"] = -5.0

    _protect_creative_choices(report, values)
    return apply_preferences_and_style(values, preferences)


def _protect_creative_choices(
    report: AnalysisReport,
    values: dict[str, float],
) -> None:
    if is_low_key(report):
        values.pop("exposureEv", None)
        if values.get("shadows", 0.0) > 6.0:
            values["shadows"] = 6.0
        if values.get("blacks", 0.0) > 4.0:
            values["blacks"] = 4.0

    if is_high_saturation(report) or is_low_saturation(report):
        values["saturation"] = min(values.get("saturation", 0.0), 0.0)
        values["vibrance"] = min(values.get("vibrance", 0.0), 0.0)

    if not is_strong_color_cast(report):
        if is_warm_ambient(report):
            values["temperature"] = max(values.get("temperature", 0.0), 0.0)
        if is_cool_ambient(report):
            values["temperature"] = min(values.get("temperature", 0.0), 0.0)


def cap_for_preferences(
    field: str,
    value: float,
    preferences: PhotographerPreferences,
) -> float:
    if preferences.preserve_original_color and field in {"temperature", "tint"}:
        value = clamp(value, -8.0, 8.0)
    if preferences.preserve_original_color and field in {"saturation", "vibrance"}:
        value = clamp(value, -8.0, 8.0)
    if not preferences.allow_stylization:
        if field in {"saturation", "vibrance"}:
            value = clamp(value, -12.0, 12.0)
        if field == "vignette":
            value = clamp(value, -8.0, 8.0)
        if field == "grain":
            value = 0.0
    return value


def apply_preferences_and_style(
    values: dict[str, float],
    preferences: PhotographerPreferences,
    style: StyleDefinition | None = None,
) -> AdjustmentIntent:
    if preferences.adjustment_strength <= 0.0:
        return AdjustmentIntent()

    naturalness_scale = 1.0 - 0.5 * preferences.naturalness
    envelope = style.envelope.model_dump(by_alias=True) if style is not None else {}
    result: dict[str, float] = {}

    for field, raw in values.items():
        value = raw * preferences.adjustment_strength
        if field in _STYLE_COLOR_FIELDS:
            value *= naturalness_scale
        value = cap_for_preferences(field, value, preferences)
        if field in _B100_FIELDS:
            value = clamp(value, -100.0, 100.0)
        elif field in _U100_FIELDS:
            value = clamp(value, 0.0, 100.0)
        elif field == "exposureEv":
            value = clamp(value, -5.0, 5.0)

        if field in envelope:
            value = clamp(value, -float(envelope[field]), float(envelope[field]))

        rounded = round2(value)
        if abs(rounded) >= 0.005:
            result[field] = rounded

    return AdjustmentIntent(**result)


__all__ = [
    "COLOR_CAST_THRESHOLD",
    "apply_preferences_and_style",
    "available_mask_ids",
    "cap_for_preferences",
    "clamp",
    "creative_choices",
    "evidence_refs_for_issue",
    "has_conflicting_issues",
    "is_balanced_frame",
    "is_cool_ambient",
    "is_creative_sensitive_issue",
    "is_flat_lighting",
    "is_high_contrast",
    "is_high_key",
    "is_high_saturation",
    "is_low_key",
    "is_low_saturation",
    "is_strong_color_cast",
    "is_warm_ambient",
    "issue_adjustments",
    "round2",
    "suggest_adjustments",
]
