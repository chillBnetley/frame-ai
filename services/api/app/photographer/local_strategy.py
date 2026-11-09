"""Prepared local strategy for style plans.

Semantic masks are created before planning so the model can reference a real
mask id; it never invents one. When segmentation is unavailable the plan falls
back to global adjustments and records the limitation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.ai.contracts import SceneLabel, SubjectType
from app.core.errors import AppError
from app.models.analysis_report import AnalysisReport
from app.models.conversion import ConversionMode
from app.models.recipe import (
    MASK_LIMIT,
    EditRecipe,
    SemanticClass,
    UserMask,
)
from app.models.style_profile import StyleProfile
from app.photographer.modes import conversion_profile
from app.photographer.rules import clamp, round2
from app.photographer.styles import strength_factor

if TYPE_CHECKING:
    from app.services.semantic_mask_service import SemanticMaskService

logger = logging.getLogger("frame_ai.photographer")

_LOCAL_HINTS = ("局部", "蒙版", "分区")
_PERSON_HINTS = ("人物", "肤色", "主体", "人像")
_SKY_HINTS = ("天空", "云", "风景", "边缘")
_LOCAL_TARGETS: dict[SemanticClass, dict[str, float]] = {
    "person": {"exposureEv": 0.08, "shadows": 4.0, "clarity": 2.0},
    "sky": {"highlights": -6.0, "saturation": 2.0, "clarity": 3.0},
}


@dataclass(frozen=True, slots=True)
class SemanticPlanning:
    recipe: EditRecipe
    mask_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def choose_semantic_class(
    profile: StyleProfile,
    report: AnalysisReport,
) -> SemanticClass | None:
    """Pick at most one region class that this archive and photo can use."""
    text = profile.post_strategy
    if not any(hint in text for hint in _LOCAL_HINTS):
        return None

    has_person = any(subject.type is SubjectType.PERSON for subject in report.subjects)
    scene = report.scene.primary
    wants_person = any(hint in text for hint in _PERSON_HINTS)
    wants_sky = any(hint in text for hint in _SKY_HINTS)

    if scene in {SceneLabel.LANDSCAPE, SceneLabel.NATURE, SceneLabel.ARCHITECTURE} and (
        wants_sky or any(hint in text for hint in _LOCAL_HINTS)
    ):
        return "sky"
    if has_person and wants_person:
        return "person"
    if has_person and scene in {SceneLabel.PORTRAIT, SceneLabel.INDOOR}:
        return "person"
    return None


def plan_semantic_masks(
    profile: StyleProfile,
    report: AnalysisReport,
    recipe: EditRecipe,
    *,
    image_id: str,
    service: SemanticMaskService | None,
) -> SemanticPlanning:
    semantic_class = choose_semantic_class(profile, report)
    if semantic_class is None:
        return SemanticPlanning(recipe=recipe)

    existing = next(
        (
            mask
            for mask in recipe.masks
            if mask.source == "semantic" and mask.semantic_class == semantic_class
        ),
        None,
    )
    if existing is not None:
        return SemanticPlanning(recipe=recipe, mask_ids=(existing.id,))

    if service is None:
        return SemanticPlanning(
            recipe=recipe,
            limitations=("语义蒙版服务未配置，局部策略已退化为全局处理。",),
        )
    if len(recipe.masks) >= MASK_LIMIT:
        return SemanticPlanning(
            recipe=recipe,
            limitations=("蒙版数量已达上限，局部策略已退化为全局处理。",),
        )

    try:
        result = service.create(image_id, semantic_class)
    except AppError as exc:
        if exc.code not in {"semantic_mask_unavailable", "semantic_mask_timeout"}:
            raise
        logger.info(
            "style_semantic_mask_degraded image_id=%s class=%s code=%s",
            image_id,
            semantic_class,
            exc.code,
        )
        return SemanticPlanning(
            recipe=recipe,
            limitations=("语义蒙版不可用，局部策略已退化为全局处理。",),
        )

    mask = UserMask(
        id=_next_mask_id(recipe, semantic_class),
        shape="semantic",
        source="semantic",
        semantic_class=semantic_class,
        matte_id=result.matte_id,
        matte_sha256=result.sha256,
        model_version=result.model_version,
        x=0.0,
        y=0.0,
        width=1.0,
        height=1.0,
    )
    updated = recipe.model_copy(update={"masks": (*recipe.masks, mask)})
    label = "人物" if semantic_class == "person" else "天空"
    return SemanticPlanning(
        recipe=updated,
        mask_ids=(mask.id,),
        notes=(f"已为局部策略准备{label}语义蒙版。",),
    )


def semantic_local_intent(
    semantic_class: SemanticClass,
    strength: float,
    mode: ConversionMode,
) -> dict[str, float]:
    """Small deterministic local deltas used by the mock and fallback planner."""
    if strength <= 0.0:
        return {}
    scale = conversion_profile(mode).local_scale
    values: dict[str, float] = {}
    for field, raw in _LOCAL_TARGETS[semantic_class].items():
        value = round2(clamp(raw * strength_factor(field, strength) * scale, -100.0, 100.0))
        if abs(value) >= 0.005:
            values[field] = value
    return values


def _next_mask_id(recipe: EditRecipe, semantic_class: SemanticClass) -> str:
    base = f"mask_semantic_{semantic_class}"
    taken = {mask.id for mask in recipe.masks}
    if base not in taken:
        return base
    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    return f"{base}_{suffix}"


__all__ = [
    "SemanticPlanning",
    "choose_semantic_class",
    "plan_semantic_masks",
    "semantic_local_intent",
]
