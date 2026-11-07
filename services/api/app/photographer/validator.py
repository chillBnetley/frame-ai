from __future__ import annotations

from decimal import Decimal

from app.models.analysis_report import AnalysisReport
from app.models.photographer import CritiqueResponse, ParameterChange
from app.models.recipe import (
    LOCAL_V1_UNSUPPORTED_FIELDS,
    Adjustments,
    EditRecipe,
)
from app.photographer.rules import (
    available_mask_ids,
    clamp,
    is_cool_ambient,
    is_high_saturation,
    is_low_key,
    is_low_saturation,
    is_strong_color_cast,
    is_warm_ambient,
)

LOW_KEY_MAX_EXPOSURE_DELTA = 0.2
LOW_KEY_MAX_SHADOW_DELTA = 6.0
LOW_KEY_MAX_BLACK_DELTA = 4.0

_ADJUSTMENT_BOUNDS: dict[str, tuple[float, float]] = {
    "exposureEv": (-5.0, 5.0),
    "contrast": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "whites": (-100.0, 100.0),
    "blacks": (-100.0, 100.0),
    "temperature": (-100.0, 100.0),
    "tint": (-100.0, 100.0),
    "saturation": (-100.0, 100.0),
    "vibrance": (-100.0, 100.0),
    "clarity": (-100.0, 100.0),
    "sharpen": (0.0, 100.0),
    "denoise": (0.0, 100.0),
    "vignette": (-100.0, 100.0),
    "grain": (0.0, 100.0),
    "rotationDeg": (-15.0, 15.0),
}
_ALLOWED_REF_PREFIXES = ("rule.",)


class RecipeValidationError(ValueError):
    def __init__(self, issues: tuple[str, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


def enforce_conflicts(
    report: AnalysisReport,
    current: Adjustments,
    values: dict[str, float],
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Clamp values so an intentional look is not mechanically corrected."""
    base = current.model_dump(by_alias=True)
    base.pop("crop", None)
    result = {**base, **{key: value for key, value in values.items() if key != "crop"}}
    warnings: list[str] = []

    if is_high_saturation(report) or is_low_saturation(report):
        saturation_capped = False
        for field in ("saturation", "vibrance"):
            if result[field] > base[field]:
                result[field] = base[field]
                saturation_capped = True
        if saturation_capped:
            warnings.append("画面色彩强度已较明确，未进一步提升饱和度。")

    if is_low_key(report):
        exposure_delta = result["exposureEv"] - base["exposureEv"]
        if exposure_delta > LOW_KEY_MAX_EXPOSURE_DELTA:
            result["exposureEv"] = base["exposureEv"] + LOW_KEY_MAX_EXPOSURE_DELTA
            warnings.append("低调画面仅允许轻微提亮，曝光提升已限制。")
        shadow_delta = result["shadows"] - base["shadows"]
        if shadow_delta > LOW_KEY_MAX_SHADOW_DELTA:
            result["shadows"] = base["shadows"] + LOW_KEY_MAX_SHADOW_DELTA
            warnings.append("低调画面的阴影提亮幅度已限制。")
        black_delta = result["blacks"] - base["blacks"]
        if black_delta > LOW_KEY_MAX_BLACK_DELTA:
            result["blacks"] = base["blacks"] + LOW_KEY_MAX_BLACK_DELTA
            warnings.append("低调画面的黑位提升幅度已限制。")

    if not is_strong_color_cast(report):
        temperature_delta = result["temperature"] - base["temperature"]
        if is_warm_ambient(report) and temperature_delta < 0.0:
            result["temperature"] = base["temperature"]
            warnings.append("暖色环境被识别为创作选择，未强制冷化。")
        if is_cool_ambient(report) and temperature_delta > 0.0:
            result["temperature"] = base["temperature"]
            warnings.append("冷色环境被识别为创作选择，未强制暖化。")

    return result, tuple(dict.fromkeys(warnings))


def conflict_violations(
    report: AnalysisReport,
    current: Adjustments,
    proposed: Adjustments,
) -> tuple[str, ...]:
    _, warnings = enforce_conflicts(report, current, proposed.model_dump(by_alias=True))
    return warnings


def validate_recipe(
    recipe: EditRecipe,
    *,
    current: EditRecipe | None = None,
    report: AnalysisReport | None = None,
    changes: tuple[ParameterChange, ...] = (),
) -> None:
    issues: list[str] = []
    issues.extend(_range_issues(recipe))
    issues.extend(_curve_issues(recipe))
    if current is not None:
        issues.extend(_protected_field_issues(recipe, current))
        issues.extend(_local_mask_issues(recipe, current))
        if report is not None:
            issues.extend(conflict_violations(report, current.adjustments, recipe.adjustments))
    else:
        issues.extend(_local_mask_issues(recipe, None))
    if report is not None and changes:
        issues.extend(_evidence_issues(report, changes))

    if issues:
        raise RecipeValidationError(tuple(dict.fromkeys(issues)))


def validate_critique(report: AnalysisReport, critique: CritiqueResponse) -> None:
    """Every critique conclusion must cite something this report actually contains."""
    known = known_evidence_refs(report)
    issues: list[str] = []
    cited: list[tuple[str, tuple[str, ...]]] = [
        (f"strength[{index}]", point.evidence_refs)
        for index, point in enumerate(critique.strengths)
    ]
    cited += [
        (f"technical.objective[{index}]", point.evidence_refs)
        for index, point in enumerate(critique.technical.objective)
    ]
    cited += [
        (f"technical.possibleIssues[{index}]", point.evidence_refs)
        for index, point in enumerate(critique.technical.possible_issues)
    ]
    for index, point in enumerate(critique.creative):
        cited.append((f"creative[{index}]", point.evidence_refs))
        if not point.subjective:
            issues.append(f"creative[{index}] must be marked subjective")
    for index, suggestion in enumerate(critique.suggestions):
        cited.append((f"suggestion[{index}]", suggestion.evidence_refs))
        if suggestion.recipe_patch is not None and not suggestion.recipe_patch.model_dump(
            exclude_none=True
        ):
            issues.append(f"suggestion[{index}] carries an empty recipePatch")

    for label, refs in cited:
        issues.extend(evidence_ref_issues(label, refs, known))
    if issues:
        raise RecipeValidationError(tuple(dict.fromkeys(issues)))


def _range_issues(recipe: EditRecipe) -> tuple[str, ...]:
    issues: list[str] = []
    values = recipe.adjustments.model_dump(by_alias=True)
    for field, (low, high) in _ADJUSTMENT_BOUNDS.items():
        value = values[field]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            issues.append(f"{field} must be a number")
            continue
        if value < low or value > high:
            issues.append(f"{field} is outside the allowed range [{low}, {high}]")
        if _decimal_places(value) > 2:
            issues.append(f"{field} must use at most two decimal places")
    crop = recipe.adjustments.crop
    if crop is not None:
        if (
            crop.x < 0
            or crop.y < 0
            or crop.w <= 0
            or crop.h <= 0
            or crop.x + crop.w > 1
            or crop.y + crop.h > 1
        ):
            issues.append("crop must lie inside the image")
    return tuple(issues)


def _curve_issues(recipe: EditRecipe) -> tuple[str, ...]:
    issues: list[str] = []
    for channel in ("master", "red", "green", "blue"):
        points = getattr(recipe.curve, channel)
        if len(points) == 1:
            issues.append(f"{channel} curve must be empty or contain at least two points")
        previous: float | None = None
        for point in points:
            if not (0.0 <= point.x <= 1.0 and 0.0 <= point.y <= 1.0):
                issues.append(f"{channel} curve points must stay inside [0, 1]")
                break
            if _decimal_places(point.x) > 6 or _decimal_places(point.y) > 6:
                issues.append(f"{channel} curve points must use at most six decimal places")
                break
            if previous is not None and point.x <= previous:
                issues.append(f"{channel} curve points must be sorted by x with unique values")
                break
            previous = point.x
    return tuple(issues)


def _protected_field_issues(recipe: EditRecipe, current: EditRecipe) -> tuple[str, ...]:
    issues: list[str] = []
    if recipe.adjustments.crop != current.adjustments.crop:
        issues.append("crop must not be changed by the planner")
    if recipe.adjustments.rotation_deg != current.adjustments.rotation_deg:
        issues.append("rotationDeg must not be changed by the planner")
    if recipe.output != current.output:
        issues.append("output settings must not be changed by the planner")
    if recipe.masks != current.masks:
        issues.append("masks must not be added, removed, or modified by the planner")
    return tuple(issues)


def _local_mask_issues(
    recipe: EditRecipe,
    current: EditRecipe | None,
) -> tuple[str, ...]:
    issues: list[str] = []
    allowed = available_mask_ids(current) if current is not None else available_mask_ids(recipe)
    for item in recipe.local_adjustments:
        if item.mask_id not in allowed:
            issues.append(f"local adjustment {item.id} references unknown maskId {item.mask_id}")
        for field in LOCAL_V1_UNSUPPORTED_FIELDS:
            if getattr(item.adjustments, field) != 0:
                issues.append(f"local adjustment {item.id} uses unsupported field {field}")
    return tuple(issues)


def known_evidence_refs(report: AnalysisReport) -> frozenset[str]:
    """Every identifier a photographer conclusion may cite for this report."""
    refs: set[str] = {"instruction"}
    for issue in report.issues:
        refs.add(issue.id)
        refs.update(issue.region_ids)
    for region in report.regions:
        refs.add(region.id)
    for subject in report.subjects:
        refs.add(subject.id)
    refs.update(_report_measurement_refs(report))
    return frozenset(refs)


def evidence_ref_issues(
    label: str,
    refs: tuple[str, ...],
    known: frozenset[str],
) -> tuple[str, ...]:
    unknown = [
        ref for ref in refs if ref not in known and not ref.startswith(_ALLOWED_REF_PREFIXES)
    ]
    return (f"{label} cites unknown evidence: {', '.join(unknown)}",) if unknown else ()


def _evidence_issues(
    report: AnalysisReport,
    changes: tuple[ParameterChange, ...],
) -> tuple[str, ...]:
    known = known_evidence_refs(report)
    issues: list[str] = []
    for change in changes:
        issues.extend(evidence_ref_issues(f"change {change.path}", change.evidence_refs, known))
    return tuple(issues)


def _report_measurement_refs(report: AnalysisReport) -> set[str]:
    refs: set[str] = set()
    sections = (
        ("measurement", report.measurements),
        ("color", report.color),
        ("lighting", report.lighting),
        ("composition", report.composition),
        ("scene", report.scene),
        ("technicalQuality", report.technical_quality),
    )
    for prefix, model in sections:
        for path in _leaf_paths(model.model_dump(by_alias=True)):
            refs.add(f"{prefix}.{path}")
    return refs


def _leaf_paths(value: object, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, entry in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_leaf_paths(entry, child))
        return tuple(paths)
    if isinstance(value, (list, tuple)):
        return ()
    return (prefix,) if prefix else ()


def _decimal_places(value: float) -> int:
    exponent = Decimal(repr(float(value))).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def clamp_adjustment(field: str, value: float) -> float:
    low, high = _ADJUSTMENT_BOUNDS[field]
    return clamp(value, low, high)


__all__ = [
    "LOW_KEY_MAX_BLACK_DELTA",
    "LOW_KEY_MAX_EXPOSURE_DELTA",
    "LOW_KEY_MAX_SHADOW_DELTA",
    "RecipeValidationError",
    "clamp_adjustment",
    "conflict_violations",
    "enforce_conflicts",
    "known_evidence_refs",
    "validate_critique",
    "validate_recipe",
]
