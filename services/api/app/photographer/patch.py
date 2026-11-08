"""Apply a natural-language patch draft to the recipe the user is looking at.

The chat path is deliberately narrower than the planning path: only the fields the
instruction mentions move, and curves, HSL, grading, masks, crop and rotation are
never touched, so an instruction cannot reset edits the user already made.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.models.analysis_report import AnalysisReport
from app.models.photographer import (
    MAX_CHANGES,
    MAX_NOTES,
    ParameterChange,
    PatchDraft,
    PhotographerPreferences,
)
from app.models.recipe import (
    LOCAL_ADJUSTMENT_LIMIT,
    LOCAL_V1_UNSUPPORTED_FIELDS,
    Adjustments,
    EditRecipe,
    LocalAdjustment,
    LocalAdjustments,
)
from app.photographer.rules import available_mask_ids, cap_for_preferences, round2
from app.photographer.validator import (
    RecipeValidationError,
    clamp_adjustment,
    enforce_conflicts,
    validate_recipe,
)

INSTRUCTION_EVIDENCE_REF = "instruction"
PATCH_ADJUSTMENT_FIELDS: tuple[str, ...] = (
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
PATCH_LOCAL_FIELDS: tuple[str, ...] = (
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


@dataclass(frozen=True, slots=True)
class PatchedRecipe:
    recipe: EditRecipe
    changes: tuple[ParameterChange, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    unsupported: tuple[str, ...]


def allowed_patch_paths(recipe: EditRecipe) -> frozenset[str]:
    """Every change path a patch may write for this recipe."""
    paths = {f"adjustments.{field}" for field in PATCH_ADJUSTMENT_FIELDS}
    paths.update(
        f"localAdjustments.{mask_id}.{field}"
        for mask_id in available_mask_ids(recipe)
        for field in PATCH_LOCAL_FIELDS
    )
    return frozenset(paths)


def apply_patch(
    current_recipe: EditRecipe,
    analysis: AnalysisReport,
    draft: PatchDraft,
    preferences: PhotographerPreferences | None = None,
) -> PatchedRecipe:
    """Turn an untrusted patch draft into the smallest validated recipe change."""
    prefs = preferences or PhotographerPreferences()
    base = current_recipe.model_copy(deep=True)

    if not draft.supported:
        return PatchedRecipe(
            recipe=base,
            changes=(),
            warnings=_merge(draft.warnings),
            limitations=_merge(draft.limitations),
            unsupported=_merge(draft.unsupported),
        )

    warnings: list[str] = []
    values = base.adjustments.model_dump(by_alias=True)
    values.pop("crop", None)
    values.pop("rotationDeg", None)
    requested = (
        draft.adjustments.model_dump(by_alias=True, exclude_none=True)
        if draft.adjustments is not None
        else {}
    )
    values = _apply_global(values, requested, prefs, warnings)
    values, conflict_warnings = enforce_conflicts(analysis, base.adjustments, values)
    warnings.extend(conflict_warnings)

    adjustments = Adjustments.model_validate(
        {field: round2(clamp_adjustment(field, values[field])) for field in PATCH_ADJUSTMENT_FIELDS}
        | {
            "rotationDeg": base.adjustments.rotation_deg,
            "crop": base.adjustments.crop,
        }
    )

    recipe = EditRecipe(
        schema_version=base.schema_version,
        style_id=base.style_id,
        style_strength=base.style_strength,
        adjustments=adjustments,
        curve=base.curve,
        hsl=base.hsl,
        color_grading=base.color_grading,
        masks=base.masks,
        local_adjustments=_merge_local(base, draft),
        output=base.output,
        rationale=base.rationale,
        warnings=base.warnings,
    )

    changes = _diff(base, recipe)
    if not changes:
        warnings.append("当前配方已满足该指令，未产生参数变化。")

    validate_recipe(recipe, current=base, report=analysis, changes=changes)
    return PatchedRecipe(
        recipe=recipe,
        changes=changes,
        warnings=_merge(warnings, draft.warnings),
        limitations=_merge(draft.limitations),
        unsupported=_merge(draft.unsupported),
    )


def _apply_global(
    values: dict[str, float],
    requested: dict[str, float],
    preferences: PhotographerPreferences,
    warnings: list[str],
) -> dict[str, float]:
    result = dict(values)
    for field, raw in requested.items():
        if field not in PATCH_ADJUSTMENT_FIELDS:
            raise RecipeValidationError((f"patch field {field} is not adjustable",))
        delta = cap_for_preferences(field, float(raw), preferences)
        if abs(delta - float(raw)) > 1e-9:
            warnings.append(f"为保留原有色彩倾向，{_FIELD_LABELS[field]}幅度已收紧。")
        proposed = clamp_adjustment(field, result[field] + delta)
        if proposed != result[field] + delta:
            warnings.append(f"{_FIELD_LABELS[field]}已到达参数上下限，实际幅度小于请求。")
        result[field] = proposed
    return result


def _merge_local(base: EditRecipe, draft: PatchDraft) -> tuple[LocalAdjustment, ...]:
    available = available_mask_ids(base)
    result = list(base.local_adjustments)

    for intent in draft.local_adjustments:
        if intent.mask_id not in available:
            raise RecipeValidationError((f"patch references unknown maskId {intent.mask_id}",))
        raw = intent.adjustments.model_dump(by_alias=True, exclude_none=True)
        unsupported = [
            field for field in LOCAL_V1_UNSUPPORTED_FIELDS if raw.get(field) not in (None, 0)
        ]
        if unsupported:
            raise RecipeValidationError(
                (f"patch uses unsupported local fields: {', '.join(unsupported)}",)
            )
        delta = {
            field: float(value)
            for field, value in raw.items()
            if field in PATCH_LOCAL_FIELDS and value not in (None, 0)
        }
        if delta:
            _merge_local_intent(result, intent.mask_id, delta)

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
            for field in PATCH_LOCAL_FIELDS
        } | {field: current[field] for field in LOCAL_V1_UNSUPPORTED_FIELDS}
        result[index] = item.model_copy(
            update={"adjustments": LocalAdjustments.model_validate(merged)}
        )
        return

    next_id = 1
    local_id = f"local_ai_{next_id}"
    while any(item.id == local_id for item in result):
        next_id += 1
        local_id = f"local_ai_{next_id}"
    if len(result) >= LOCAL_ADJUSTMENT_LIMIT:
        raise RecipeValidationError(
            (f"at most {LOCAL_ADJUSTMENT_LIMIT} local adjustments are allowed",)
        )
    result[:] = [item.model_copy(update={"order": index}) for index, item in enumerate(result)]
    merged = {
        field: round2(clamp_adjustment(field, delta.get(field, 0.0)))
        for field in PATCH_LOCAL_FIELDS
    }
    result.append(
        LocalAdjustment(
            id=local_id,
            mask_id=mask_id,
            order=len(result),
            adjustments=LocalAdjustments.model_validate(merged),
        )
    )


def _diff(base: EditRecipe, recipe: EditRecipe) -> tuple[ParameterChange, ...]:
    changes: list[ParameterChange] = []
    previous = base.adjustments.model_dump(by_alias=True)
    proposed = recipe.adjustments.model_dump(by_alias=True)
    for field in PATCH_ADJUSTMENT_FIELDS:
        if previous[field] == proposed[field]:
            continue
        changes.append(
            ParameterChange(
                path=f"adjustments.{field}",
                previous=previous[field],
                proposed=proposed[field],
                reason=f"按指令调整{_FIELD_LABELS[field]}。",
                evidence_refs=(INSTRUCTION_EVIDENCE_REF,),
            )
        )

    base_local = {item.mask_id: item.adjustments for item in base.local_adjustments}
    for item in recipe.local_adjustments:
        old_values = _local_values(base_local.get(item.mask_id))
        new_values = item.adjustments.model_dump(by_alias=True)
        for field in PATCH_LOCAL_FIELDS:
            old_value = old_values[field]
            if old_value == new_values[field]:
                continue
            changes.append(
                ParameterChange(
                    path=f"localAdjustments.{item.mask_id}.{field}",
                    previous=old_value,
                    proposed=new_values[field],
                    reason=f"按指令调整已有蒙版的{_FIELD_LABELS[field]}。",
                    evidence_refs=(INSTRUCTION_EVIDENCE_REF,),
                )
            )

    return tuple(changes[:MAX_CHANGES])


def _local_values(adjustments: LocalAdjustments | None) -> dict[str, float]:
    if adjustments is None:
        return dict.fromkeys(PATCH_LOCAL_FIELDS, 0.0)
    values = adjustments.model_dump(by_alias=True)
    return {field: float(values[field]) for field in PATCH_LOCAL_FIELDS}


def _merge(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(note for group in groups for note in group))[:MAX_NOTES]


__all__ = [
    "INSTRUCTION_EVIDENCE_REF",
    "PATCH_ADJUSTMENT_FIELDS",
    "PATCH_LOCAL_FIELDS",
    "PatchedRecipe",
    "allowed_patch_paths",
    "apply_patch",
]
