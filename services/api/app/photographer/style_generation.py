"""Dynamic style decisions shared by the mock planner and the fallback path.

The real provider reads the archive and decides from it. This module only keeps
the behaviour deterministic when no model is available: it turns the archive's
structured constraints and the stage 3 report into bounded style deltas. It is
not a second colour engine; every value still flows through the stage 5
generator and the stage 4 validator.
"""

from __future__ import annotations

from app.ai.contracts import SceneLabel
from app.ai.style_context import StyleFitContext, StyleGenerationContext
from app.models.analysis_report import AnalysisReport
from app.models.conversion import ConversionMode
from app.models.photographer import (
    DirectionConstraint,
    PhotographerPreferences,
)
from app.models.style_profile import StyleProfile
from app.photographer.modes import (
    constrain_style_values,
    conversion_profile,
)
from app.photographer.rules import (
    clamp,
    is_flat_lighting,
    is_high_contrast,
    is_high_saturation,
    is_low_key,
    is_low_saturation,
    is_strong_color_cast,
    round2,
)
from app.photographer.styles import strength_factor
from app.styles.fit import evaluate_style_fit

_ENGINE_SEEDS: dict[str, dict[str, float]] = {
    "natural": {},
    "portrait": {"vibrance": 6.0, "clarity": 4.0, "vignette": 4.0},
    "landscape": {"vibrance": 14.0, "clarity": 10.0, "highlights": -10.0, "shadows": 8.0},
    "street": {"contrast": 12.0, "clarity": 8.0, "vibrance": 4.0, "grain": 6.0},
    "documentary": {"contrast": 6.0, "clarity": 4.0},
    "film": {
        "contrast": 8.0,
        "highlights": -8.0,
        "shadows": 10.0,
        "temperature": 5.0,
        "saturation": -3.0,
        "grain": 14.0,
        "vignette": 6.0,
    },
    "cinematic": {
        "contrast": 14.0,
        "highlights": -10.0,
        "shadows": 8.0,
        "vibrance": 6.0,
        "vignette": 10.0,
        "grain": 5.0,
    },
}

_SCENE_SEEDS: dict[SceneLabel, dict[str, float]] = {
    SceneLabel.PORTRAIT: {"clarity": -2.0, "vibrance": 2.0, "vignette": 2.0},
    SceneLabel.LANDSCAPE: {"vibrance": 3.0, "clarity": 2.0},
    SceneLabel.STREET: {"contrast": 2.0},
    SceneLabel.ARCHITECTURE: {"clarity": 3.0, "vignette": 2.0},
    SceneLabel.NIGHT: {"exposureEv": 0.05, "denoise": 4.0, "grain": -2.0},
    SceneLabel.INDOOR: {"exposureEv": 0.05, "contrast": 2.0},
    SceneLabel.FOOD: {"temperature": 2.0, "vibrance": 3.0},
    SceneLabel.NATURE: {"vibrance": 2.0},
    SceneLabel.OTHER: {},
}

_SKIN_FIELDS = ("saturation", "vibrance", "temperature", "tint")


def build_style_context(
    profile: StyleProfile,
    report: AnalysisReport,
    *,
    mode: ConversionMode,
    strength: float,
    image_id: str,
    image_sha256: str,
) -> StyleGenerationContext:
    evaluation = evaluate_style_fit(profile, report)
    return StyleGenerationContext(
        image_id=image_id,
        image_sha256=image_sha256.lower(),
        profile=profile,
        fit=StyleFitContext.from_evaluation(evaluation),
        conversion_mode=mode,
        strength=strength,
        mode_info=conversion_profile(mode).info(),
    )


def dynamic_style_adjustments(
    profile: StyleProfile,
    report: AnalysisReport,
    *,
    mode: ConversionMode,
    strength: float,
    preferences: PhotographerPreferences,
) -> dict[str, float]:
    """Photo-aware deterministic deltas at the requested continuous strength."""
    if strength <= 0.0 or preferences.adjustment_strength <= 0.0:
        return {}

    style = profile.to_style_definition()
    targets = _dynamic_targets(profile, report)
    personal = getattr(profile, "personal", None)
    if personal is not None:
        targets.update(personal.targets)
        scene_targets = personal.scene_targets.get(report.scene.primary)
        if scene_targets:
            targets.update(scene_targets)
    targets = _apply_constraints(profile, report, targets)
    naturalness_scale = 1.0 - 0.5 * preferences.naturalness
    identity_fields = _colour_mode_fields(profile)

    scaled: dict[str, float] = {}
    for field, raw in targets.items():
        value = raw * strength_factor(field, strength, identity=field in identity_fields)
        if field not in identity_fields:
            value *= naturalness_scale
        scaled[field] = round2(value)

    constrained = constrain_style_values(scaled, style, mode)
    envelope = style.envelope.model_dump(by_alias=True)
    return {
        field: value
        for field, value in constrained.items()
        if field in envelope and abs(value) >= 0.005
    }


def _dynamic_targets(profile: StyleProfile, report: AnalysisReport) -> dict[str, float]:
    values = dict(_ENGINE_SEEDS.get(profile.engine_style, {}))
    for field, delta in _SCENE_SEEDS.get(report.scene.primary, {}).items():
        values[field] = values.get(field, 0.0) + delta

    saturation_hint = _saturation_hint(profile)
    if saturation_hint is not None:
        values["saturation"] = saturation_hint
    if "高对比" in profile.light.contrast:
        values["contrast"] = values.get("contrast", 0.0) + 4.0
    if "颗粒" in profile.texture.grain:
        values["grain"] = max(values.get("grain", 0.0), 6.0)
    if "漫射" in profile.light.expression or "柔和" in profile.light.contrast:
        values["contrast"] = values.get("contrast", 0.0) - 3.0

    if is_flat_lighting(report):
        values["contrast"] = values.get("contrast", 0.0) * 1.25 + 2.0
        values["shadows"] = values.get("shadows", 0.0) + 2.0
    elif is_high_contrast(report):
        values["contrast"] = values.get("contrast", 0.0) * 0.7
        values["highlights"] = values.get("highlights", 0.0) - 3.0
        values["shadows"] = values.get("shadows", 0.0) + 3.0

    if is_low_key(report):
        values["exposureEv"] = min(values.get("exposureEv", 0.0), 0.0)
        values["shadows"] = min(values.get("shadows", 0.0), 4.0)
    if is_high_saturation(report):
        values["saturation"] = min(values.get("saturation", 0.0), 0.0)
        values["vibrance"] = min(values.get("vibrance", 0.0), 0.0)
    elif is_low_saturation(report) and saturation_hint != -100.0:
        # A low-saturation source must not cancel a monochrome style: the
        # archive's identity colour mode is the explicit reason it was chosen.
        values["saturation"] = max(values.get("saturation", 0.0), 0.0)

    if is_strong_color_cast(report):
        values.setdefault("temperature", 0.0)
        values.setdefault("tint", 0.0)

    return values


def _apply_constraints(
    profile: StyleProfile,
    report: AnalysisReport,
    values: dict[str, float],
) -> dict[str, float]:
    constraints = set(profile.constraints)
    result = dict(values)

    if constraints & {
        DirectionConstraint.MAINTAIN_NEUTRALITY,
        DirectionConstraint.AVOID_COLOR_CAST,
    }:
        result["temperature"] = 0.0
        result["tint"] = 0.0
    elif DirectionConstraint.KEEP_WARM_TONES in constraints:
        result["temperature"] = max(result.get("temperature", 0.0), 2.0)

    if DirectionConstraint.KEEP_LOW_KEY in constraints:
        result["exposureEv"] = min(result.get("exposureEv", 0.0), 0.0)
        result["shadows"] = min(result.get("shadows", 0.0), 4.0)
        result["blacks"] = min(result.get("blacks", 0.0), 2.0)

    if DirectionConstraint.PRESERVE_HIGHLIGHT_DETAIL in constraints:
        result["highlights"] = min(result.get("highlights", 0.0), -3.0)
        result["whites"] = min(result.get("whites", 0.0), -2.0)
    if DirectionConstraint.PRESERVE_SHADOW_DETAIL in constraints:
        result["shadows"] = max(result.get("shadows", 0.0), 3.0)

    if (
        DirectionConstraint.AVOID_EXTREME_SATURATION in constraints
        and _saturation_hint(profile) != -100.0
    ):
        result["saturation"] = clamp(result.get("saturation", 0.0), -12.0, 12.0)
        result["vibrance"] = clamp(result.get("vibrance", 0.0), -10.0, 10.0)
    if DirectionConstraint.AVOID_EXTREME_CONTRAST in constraints:
        result["contrast"] = clamp(result.get("contrast", 0.0), -20.0, 20.0)

    if DirectionConstraint.PRESERVE_SKIN_TONE in constraints and report.subjects:
        for field in _SKIN_FIELDS:
            if field in result:
                result[field] = round2(result[field] * 0.7)
    if DirectionConstraint.NATURAL_LOOK in constraints:
        for field in result:
            result[field] = round2(result[field] * 0.75)

    return result


def _saturation_hint(profile: StyleProfile) -> float | None:
    text = f"{profile.color.tendency}{profile.color.saturation}"
    if any(phrase in text for phrase in ("完全去饱和", "去饱和至单色", "纯黑白", "黑白影调")):
        return -100.0
    if "低饱和" in text:
        return -12.0
    if any(word in text for word in ("高饱和", "鲜艳", "浓郁")):
        return 6.0
    return None


def _colour_mode_fields(profile: StyleProfile) -> frozenset[str]:
    return frozenset({"saturation"}) if _saturation_hint(profile) == -100.0 else frozenset()


__all__ = ["build_style_context", "dynamic_style_adjustments"]
