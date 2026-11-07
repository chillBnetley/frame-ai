from __future__ import annotations

from dataclasses import dataclass

from app.ai.contracts import IssueType
from app.models.analysis_report import AnalysisReport
from app.models.photographer import (
    MAX_CHANGES,
    ParameterChange,
    PhotographerPreferences,
    PlannerDraft,
    StyleDefinition,
)
from app.models.recipe import (
    LOCAL_ADJUSTMENT_LIMIT,
    LOCAL_V1_UNSUPPORTED_FIELDS,
    Adjustments,
    ColorGrading,
    CurveSet,
    EditRecipe,
    LocalAdjustment,
    LocalAdjustments,
)
from app.photographer.rules import (
    available_mask_ids,
    cap_for_preferences,
    clamp,
    round2,
    suggest_adjustments,
)
from app.photographer.styles import (
    style_adjustment_intent,
    style_curve_points,
    style_grading,
    style_local_intent,
)
from app.photographer.validator import (
    RecipeValidationError,
    clamp_adjustment,
    enforce_conflicts,
    validate_recipe,
)

_ADJUSTMENT_FIELDS: tuple[str, ...] = (
    "exposureEv",
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
    "sharpen",
    "denoise",
    "vignette",
    "grain",
)
_LOCAL_FIELDS: tuple[str, ...] = (
    "exposureEv",
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
)
_FIELD_LABELS: dict[str, str] = {
    "exposureEv": "曝光",
    "contrast": "对比度",
    "highlights": "高光",
    "shadows": "阴影",
    "whites": "白色色阶",
    "blacks": "黑色色阶",
    "temperature": "色温",
    "tint": "色调",
    "saturation": "饱和度",
    "vibrance": "自然饱和度",
    "clarity": "清晰度",
    "sharpen": "锐化",
    "denoise": "降噪",
    "vignette": "暗角",
    "grain": "颗粒",
}
_FIELD_ISSUES: dict[str, frozenset[IssueType]] = {
    "exposureEv": frozenset(
        {IssueType.UNDEREXPOSURE, IssueType.OVEREXPOSURE, IssueType.SUBJECT_UNDEREXPOSURE}
    ),
    "contrast": frozenset({IssueType.HARSH_CONTRAST, IssueType.FLAT_LIGHTING}),
    "highlights": frozenset(
        {IssueType.HIGHLIGHT_CLIPPING, IssueType.BACKGROUND_OVEREXPOSURE, IssueType.OVEREXPOSURE}
    ),
    "shadows": frozenset({IssueType.SHADOW_CLIPPING, IssueType.UNDEREXPOSURE}),
    "whites": frozenset({IssueType.HIGHLIGHT_CLIPPING, IssueType.OVEREXPOSURE}),
    "blacks": frozenset({IssueType.SHADOW_CLIPPING}),
    "temperature": frozenset({IssueType.COLOR_CAST, IssueType.TEMPERATURE_MISMATCH}),
    "tint": frozenset({IssueType.COLOR_CAST}),
    "saturation": frozenset({IssueType.SATURATION_ISSUE, IssueType.COLOR_HIERARCHY_ISSUE}),
    "vibrance": frozenset({IssueType.SATURATION_ISSUE, IssueType.COLOR_HIERARCHY_ISSUE}),
    "clarity": frozenset({IssueType.FOCUS_ISSUE, IssueType.LOW_DETAIL}),
    "sharpen": frozenset({IssueType.FOCUS_ISSUE, IssueType.MOTION_BLUR, IssueType.LOW_DETAIL}),
    "denoise": frozenset({IssueType.HIGH_NOISE}),
}


@dataclass(frozen=True, slots=True)
class GeneratedRecipe:
    recipe: EditRecipe
    changes: tuple[ParameterChange, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]


def generate_recipe(
    current_recipe: EditRecipe,
    analysis: AnalysisReport,
    draft: PlannerDraft,
    preferences: PhotographerPreferences | None = None,
    style: StyleDefinition | None = None,
    style_strength: float | None = None,
) -> GeneratedRecipe:
    """Turn an untrusted planner draft into a validated recipe based on the current recipe."""
    prefs = preferences or PhotographerPreferences()
    base = current_recipe.model_copy(deep=True)
    if style is None:
        strength = 0.0
    elif style_strength is None:
        strength = style.default_strength
    else:
        strength = clamp(style_strength, 0.0, 1.0)

    warnings: list[str] = []
    values = base.adjustments.model_dump(by_alias=True)
    values.pop("crop", None)
    values.pop("rotationDeg", None)
    intent, style_intent = _planned_intent(analysis, draft, prefs, style, strength, warnings)
    values = _apply_intent(values, intent, style_intent, prefs, style, warnings)
    values, conflict_warnings = enforce_conflicts(analysis, base.adjustments, values)
    warnings.extend(conflict_warnings)
    adjustments = Adjustments.model_validate(
        {field: round2(clamp_adjustment(field, values[field])) for field in _ADJUSTMENT_FIELDS}
        | {"rotationDeg": base.adjustments.rotation_deg, "crop": base.adjustments.crop}
    )

    curve = _style_curve(base.curve, style, strength, warnings)
    color_grading = _style_colour_grading(base.color_grading, style, strength, warnings)
    local_adjustments = _merge_local_adjustments(base, draft, style, strength, warnings)

    recipe = EditRecipe(
        schema_version=base.schema_version,
        style_id=style.engine_style if style is not None else base.style_id,
        style_strength=(round2(strength * 100.0) if style is not None else base.style_strength),
        adjustments=adjustments,
        curve=curve,
        hsl=base.hsl,
        color_grading=color_grading,
        masks=base.masks,
        local_adjustments=local_adjustments,
        output=base.output,
        rationale=base.rationale,
        warnings=base.warnings,
    )

    fallback_ref = "rule.style" if style is not None else "rule.auto"
    changes = _changes(base, recipe, draft, fallback_ref, warnings)
    if not changes:
        warnings.append("当前参数已足够，未生成新的像素调整。")
    if style is not None and strength <= 0.0:
        warnings.append("风格强度为 0，未应用风格参数。")

    validate_recipe(recipe, current=base, report=analysis, changes=changes)
    return GeneratedRecipe(
        recipe=recipe,
        changes=changes,
        warnings=tuple(dict.fromkeys(warnings))[:8],
        limitations=tuple(draft.limitations)[:8],
    )


def _planned_intent(
    analysis: AnalysisReport,
    draft: PlannerDraft,
    preferences: PhotographerPreferences,
    style: StyleDefinition | None,
    strength: float,
    warnings: list[str],
) -> tuple[dict[str, float], dict[str, float]]:
    has_findings = bool(draft.diagnosis.confirmed or draft.diagnosis.possible or analysis.issues)
    intent: dict[str, float] = {}
    if has_findings:
        rule_values = suggest_adjustments(analysis, preferences, style).model_dump(
            by_alias=True, exclude_none=True
        )
        model_values = draft.adjustments.model_dump(by_alias=True, exclude_none=True)
        intent.update(rule_values)
        intent.update(model_values)
    elif style is None and draft.adjustments.model_dump(exclude_none=True):
        warnings.append("诊断没有明确问题，已忽略模型提出的额外参数调整。")

    style_intent = (
        style_adjustment_intent(style, strength, preferences) if style is not None else {}
    )
    return (
        {field: value for field, value in intent.items() if field in _ADJUSTMENT_FIELDS},
        {field: value for field, value in style_intent.items() if field in _ADJUSTMENT_FIELDS},
    )


def _apply_intent(
    values: dict[str, float],
    intent: dict[str, float],
    style_intent: dict[str, float],
    preferences: PhotographerPreferences,
    style: StyleDefinition | None,
    warnings: list[str],
) -> dict[str, float]:
    envelope = style.envelope.model_dump(by_alias=True) if style is not None else {}
    result = dict(values)
    for field, raw in intent.items():
        delta = cap_for_preferences(field, raw, preferences)
        if field in envelope:
            limit = float(envelope[field])
            delta = clamp(delta, -limit, limit)
        result[field] = result[field] + delta
    for field, delta in style_intent.items():
        result[field] = result[field] + delta
    if style is not None and envelope:
        for field in _ADJUSTMENT_FIELDS:
            if field in envelope:
                limit = float(envelope[field])
                delta = result[field] - values[field]
                if abs(delta) > limit + 1e-9:
                    warnings.append(f"风格参数 {field} 超出包络，已限制。")
                    result[field] = values[field] + clamp(delta, -limit, limit)
    return result


def _style_curve(
    current: CurveSet,
    style: StyleDefinition | None,
    strength: float,
    warnings: list[str],
) -> CurveSet:
    if style is None:
        return current
    points = style_curve_points(style.id, strength)
    if not points:
        return current
    if current.master:
        warnings.append("当前主曲线由用户设置，已跳过风格曲线覆盖。")
        return current
    return current.model_copy(update={"master": points})


def _style_colour_grading(
    current: ColorGrading,
    style: StyleDefinition | None,
    strength: float,
    warnings: list[str],
) -> ColorGrading:
    if style is None:
        return current
    proposal = style_grading(style.id, strength)
    if proposal is None:
        return current
    if not _is_neutral_grading(current):
        warnings.append("当前色彩分级由用户设置，已跳过风格分级覆盖。")
        return current
    return proposal


def _is_neutral_grading(grading: ColorGrading) -> bool:
    return (
        grading.shadows.hue == 0.0
        and grading.shadows.saturation == 0.0
        and grading.midtones.hue == 0.0
        and grading.midtones.saturation == 0.0
        and grading.highlights.hue == 0.0
        and grading.highlights.saturation == 0.0
        and grading.balance == 0.0
        and grading.blending == 50.0
    )


def _merge_local_adjustments(
    base: EditRecipe,
    draft: PlannerDraft,
    style: StyleDefinition | None,
    strength: float,
    warnings: list[str],
) -> tuple[LocalAdjustment, ...]:
    available = available_mask_ids(base)
    for intent in draft.local_adjustments:
        if intent.mask_id not in available:
            raise RecipeValidationError(
                (f"local adjustment references unknown maskId {intent.mask_id}",)
            )

    intents: list[tuple[str, dict[str, float]]] = []
    for intent in draft.local_adjustments:
        raw = intent.adjustments.model_dump(by_alias=True, exclude_none=True)
        unsupported = [
            field for field in LOCAL_V1_UNSUPPORTED_FIELDS if raw.get(field) not in (None, 0)
        ]
        if unsupported:
            raise RecipeValidationError(
                (f"local adjustment uses unsupported fields: {', '.join(unsupported)}",)
            )
        delta = {field: float(value) for field, value in raw.items() if value not in (None, 0)}
        if delta:
            intents.append((intent.mask_id, delta))

    result = list(base.local_adjustments)
    if style is not None:
        style_delta = style_local_intent(style.id, strength)
        if style_delta:
            # Styles reshape the masks the user already drew; the planner never adds one.
            if base.masks:
                intents.append((base.masks[0].id, style_delta))
            else:
                warnings.append("风格包含局部调整策略，但当前画面没有可用蒙版，未应用。")

    for mask_id, delta in intents:
        _merge_local_intent(result, mask_id, delta)

    if len(result) > LOCAL_ADJUSTMENT_LIMIT:
        raise RecipeValidationError(
            (f"at most {LOCAL_ADJUSTMENT_LIMIT} local adjustments are allowed",)
        )
    return tuple(result)


def _merge_local_intent(
    result: list[LocalAdjustment],
    mask_id: str,
    delta: dict[str, float],
) -> None:
    for index, item in enumerate(result):
        if item.mask_id != mask_id:
            continue
        current = item.adjustments.model_dump(by_alias=True)
        merged = {
            field: round2(clamp_adjustment(field, current[field] + delta.get(field, 0.0)))
            for field in _LOCAL_FIELDS
        }
        result[index] = item.model_copy(
            update={"adjustments": LocalAdjustments.model_validate(merged)}
        )
        return

    next_id = 1
    local_id = f"local_ai_{next_id}"
    while any(item.id == local_id for item in result):
        next_id += 1
        local_id = f"local_ai_{next_id}"
    merged = {
        field: round2(clamp_adjustment(field, delta.get(field, 0.0))) for field in _LOCAL_FIELDS
    }
    result.append(
        LocalAdjustment(
            id=local_id,
            mask_id=mask_id,
            adjustments=LocalAdjustments.model_validate(merged),
        )
    )


def _changes(
    base: EditRecipe,
    recipe: EditRecipe,
    draft: PlannerDraft,
    fallback_ref: str,
    warnings: list[str],
) -> tuple[ParameterChange, ...]:
    changes: list[ParameterChange] = []
    previous = base.adjustments.model_dump(by_alias=True)
    proposed = recipe.adjustments.model_dump(by_alias=True)
    for field in _ADJUSTMENT_FIELDS:
        if previous[field] == proposed[field]:
            continue
        changes.append(
            ParameterChange(
                path=f"adjustments.{field}",
                previous=previous[field],
                proposed=proposed[field],
                reason=f"根据诊断证据调整{_FIELD_LABELS[field]}。",
                evidence_refs=_refs_for_field(field, draft, fallback_ref),
            )
        )

    if base.curve.master != recipe.curve.master:
        changes.append(
            ParameterChange(
                path="curve.master",
                previous=[{"x": point.x, "y": point.y} for point in base.curve.master],
                proposed=[{"x": point.x, "y": point.y} for point in recipe.curve.master],
                reason="应用风格曲线预设。",
                evidence_refs=(fallback_ref,),
            )
        )

    previous_grading = base.color_grading.model_dump(by_alias=True, mode="json")
    proposed_grading = recipe.color_grading.model_dump(by_alias=True, mode="json")
    if previous_grading != proposed_grading:
        changes.append(
            ParameterChange(
                path="colorGrading",
                previous=previous_grading,
                proposed=proposed_grading,
                reason="应用风格色彩分级。",
                evidence_refs=(fallback_ref,),
            )
        )

    base_local = {item.mask_id: item.adjustments for item in base.local_adjustments}
    for item in recipe.local_adjustments:
        old = base_local.get(item.mask_id)
        old_values = old.model_dump(by_alias=True) if old is not None else {}
        new_values = item.adjustments.model_dump(by_alias=True)
        for field in _LOCAL_FIELDS:
            old_value = old_values.get(field, 0.0)
            if old_value == new_values[field]:
                continue
            changes.append(
                ParameterChange(
                    path=f"localAdjustments.{item.mask_id}.{field}",
                    previous=old_value,
                    proposed=new_values[field],
                    reason=f"调整局部{_FIELD_LABELS[field]}。",
                    evidence_refs=_refs_for_field(field, draft, fallback_ref),
                )
            )

    if len(changes) > MAX_CHANGES:
        warnings.append(f"变更较多，仅列出前 {MAX_CHANGES} 条参数变化。")
    return tuple(changes[:MAX_CHANGES])


def _refs_for_field(
    field: str,
    draft: PlannerDraft,
    fallback_ref: str,
) -> tuple[str, ...]:
    items = (*draft.diagnosis.confirmed, *draft.diagnosis.possible)
    relevant = [item for item in items if item.type in _FIELD_ISSUES.get(field, frozenset())]
    refs = [ref for item in (relevant or items) for ref in item.evidence_refs]
    if not refs:
        refs = [ref for choice in draft.diagnosis.creative_choices for ref in choice.evidence_refs]
    if not refs:
        refs = [fallback_ref]
    return tuple(dict.fromkeys(refs))[:4]


__all__ = ["GeneratedRecipe", "generate_recipe"]
