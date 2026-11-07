"""Derive what a feedback record means, without ever claiming quality uplift."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from app.models.photographer import (
    MAX_CHANGE_FREQUENCY_ROWS,
    MAX_FEEDBACK_PATHS,
    FeedbackAction,
    FeedbackChangeFrequency,
    FeedbackDimension,
    FeedbackDimensionAverage,
    FeedbackRubric,
    FeedbackSource,
    FeedbackSourceCounts,
    FeedbackSummary,
)
from app.models.recipe import EditRecipe, recipe_hash
from app.repositories.photographer_repo import PhotographerFeedbackRecord

# Feedback answers "which parameters did this decision move", so provenance and prose
# fields stay out of the comparison; only photographic state counts as a change.
_NON_PARAMETER_FIELDS = frozenset({"schemaVersion", "rationale", "warnings", "output"})

_DISCLAIMERS: tuple[str, ...] = (
    "接受、拒绝、修改与重置只记录用户行为，不代表方案在客观质量上更优。",
    "评分是人工主观打分，没有质量基准校准，也不与自动指标混用。",
    "mock 分组来自模拟 Provider，只用于流程验证，不能代表真实模型效果。",
)

_MISSING = object()


def _leaves(value: Any, path: str, sink: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if not value:
            sink[path] = ()
            return
        for key, child in value.items():
            if key in _NON_PARAMETER_FIELDS:
                continue
            _leaves(child, f"{path}.{key}" if path else str(key), sink)
        return
    sink[path] = value


def flatten_recipe(recipe: EditRecipe) -> dict[str, Any]:
    """Every photographic leaf of a recipe, keyed by its dotted path."""
    sink: dict[str, Any] = {}
    _leaves(recipe.model_dump(by_alias=True, mode="json"), "", sink)
    return sink


def changed_paths(base: EditRecipe | None, final: EditRecipe) -> tuple[str, ...]:
    """Every parameter path that differs between two recipes, in sorted order."""
    final_leaves = flatten_recipe(final)
    base_leaves = {} if base is None else flatten_recipe(base)
    moved = [
        path for path, value in final_leaves.items() if value != base_leaves.get(path, _MISSING)
    ]
    # A null container that became an object is already covered by its own fields.
    moved_paths = set(moved)
    removed = [
        path
        for path in base_leaves
        if path not in final_leaves
        and not any(child.startswith(f"{path}.") for child in moved_paths)
    ]
    return tuple(sorted(dict.fromkeys([*moved, *removed]))[:MAX_FEEDBACK_PATHS])


def derive_action(
    *,
    action: FeedbackAction,
    plan_recipe: EditRecipe | None,
    revision_recipe: EditRecipe | None,
) -> FeedbackAction:
    """An accepted proposal only stays accepted while the stored recipe still matches it."""
    if action is not FeedbackAction.ACCEPTED or plan_recipe is None or revision_recipe is None:
        return action
    if recipe_hash(plan_recipe) == recipe_hash(revision_recipe):
        return action
    return FeedbackAction.MODIFIED


def rubric_values(rubric: FeedbackRubric | None) -> dict[str, int] | None:
    """Only the dimensions the user actually scored."""
    if rubric is None:
        return None
    scored = {
        dimension: score for dimension, score in rubric.model_dump().items() if score is not None
    }
    return scored or None


def _source_counts(records: Sequence[PhotographerFeedbackRecord]) -> FeedbackSourceCounts:
    counts = Counter(record.source for record in records)
    return FeedbackSourceCounts(
        plan=counts[FeedbackSource.PLAN.value],
        chat=counts[FeedbackSource.CHAT.value],
        critique=counts[FeedbackSource.CRITIQUE.value],
        unset=counts[None],
    )


def _change_frequency(
    records: Sequence[PhotographerFeedbackRecord],
) -> tuple[FeedbackChangeFrequency, ...]:
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(record.changed_paths)
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return tuple(FeedbackChangeFrequency(path=path, count=count) for path, count in ranked)[
        :MAX_CHANGE_FREQUENCY_ROWS
    ]


def _rubric_averages(
    records: Sequence[PhotographerFeedbackRecord],
) -> tuple[FeedbackDimensionAverage, ...]:
    scores: dict[FeedbackDimension, list[int]] = {dimension: [] for dimension in FeedbackDimension}
    by_value = {dimension.value: dimension for dimension in FeedbackDimension}
    for record in records:
        for key, score in (record.rubric or {}).items():
            dimension = by_value.get(key)
            if dimension is not None:
                scores[dimension].append(score)
    return tuple(
        FeedbackDimensionAverage(
            dimension=dimension,
            average=round(sum(values) / len(values), 2),
            count=len(values),
        )
        for dimension, values in scores.items()
        if values
    )


def summarize(records: Sequence[PhotographerFeedbackRecord]) -> FeedbackSummary:
    actions = Counter(record.action for record in records)
    return FeedbackSummary(
        total=len(records),
        accepted=actions[FeedbackAction.ACCEPTED.value],
        rejected=actions[FeedbackAction.REJECTED.value],
        modified=actions[FeedbackAction.MODIFIED.value],
        reset=actions[FeedbackAction.RESET.value],
        by_source=_source_counts(records),
        mock_count=sum(1 for record in records if record.is_mock),
        real_count=sum(1 for record in records if not record.is_mock),
        degraded_count=sum(1 for record in records if record.degraded),
        rated_count=sum(1 for record in records if record.rubric),
        change_frequency=_change_frequency(records),
        rubric_averages=_rubric_averages(records),
        disclaimers=_DISCLAIMERS,
    )


__all__ = [
    "changed_paths",
    "derive_action",
    "flatten_recipe",
    "rubric_values",
    "summarize",
]
