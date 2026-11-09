from __future__ import annotations

import pytest

from app.ai.base import PlannerRequest
from app.ai.contracts import SceneLabel
from app.ai.providers.mock import MockPlannerProvider
from app.core.errors import AppError
from app.models.conversion import ConversionMode
from app.models.photographer import PhotographerPreferences, PlannerMode
from app.models.recipe import LocalAdjustment, LocalAdjustments, UserMask
from app.photographer.generator import generate_recipe
from app.photographer.local_strategy import (
    choose_semantic_class,
    plan_semantic_masks,
    semantic_local_intent,
)
from app.photographer.style_generation import build_style_context
from app.photographer.validator import RecipeValidationError, validate_recipe
from app.services.semantic_mask_service import SemanticMaskResult
from app.styles.library import (
    BW_DOCUMENTARY,
    ENVIRONMENTAL_PORTRAIT,
    NATURE_LANDSCAPE,
    POETIC_STREET,
    RETRO_FILM,
)
from tests.photographer_support import recipe, report

_PREFS = PhotographerPreferences(naturalness=0.3, adjustment_strength=1.0)
_MODES = (ConversionMode.NATURAL, ConversionMode.STYLE, ConversionMode.CREATIVE)


class FakeSemanticService:
    def __init__(self, *, error: AppError | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.error = error

    def create(self, image_id: str, semantic_class: str) -> SemanticMaskResult:
        self.calls.append((image_id, semantic_class))
        if self.error is not None:
            raise self.error
        return SemanticMaskResult(
            matte_id="a" * 64,
            sha256="b" * 64,
            model_version="1",
            semantic_class=semantic_class,  # type: ignore[arg-type]
            width=64,
            height=48,
        )


def _semantic_mask(mask_id: str = "mask_semantic_person") -> UserMask:
    return UserMask.model_validate(
        {
            "id": mask_id,
            "shape": "semantic",
            "source": "semantic",
            "semanticClass": "person",
            "matteId": "c" * 64,
            "matteSha256": "d" * 64,
            "modelVersion": "1",
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
        }
    )


def test_semantic_class_follows_the_archive_photo_and_local_strategy():
    assert (
        choose_semantic_class(ENVIRONMENTAL_PORTRAIT, report(scene=SceneLabel.PORTRAIT)) == "person"
    )
    assert choose_semantic_class(NATURE_LANDSCAPE, report(scene=SceneLabel.LANDSCAPE)) == "sky"
    assert choose_semantic_class(POETIC_STREET, report(scene=SceneLabel.STREET)) == "person"
    assert choose_semantic_class(BW_DOCUMENTARY, report(scene=SceneLabel.STREET)) is None
    assert choose_semantic_class(RETRO_FILM, report(scene=SceneLabel.PORTRAIT)) is None


def test_semantic_planning_creates_a_real_mask_for_the_planner():
    service = FakeSemanticService()

    planning = plan_semantic_masks(
        ENVIRONMENTAL_PORTRAIT,
        report(scene=SceneLabel.PORTRAIT),
        recipe(),
        image_id="image-1",
        service=service,
    )

    assert service.calls == [("image-1", "person")]
    assert planning.mask_ids == ("mask_semantic_person",)
    assert planning.notes
    assert planning.limitations == ()
    assert planning.recipe.masks == (
        UserMask(
            id="mask_semantic_person",
            shape="semantic",
            source="semantic",
            semantic_class="person",
            matte_id="a" * 64,
            matte_sha256="b" * 64,
            model_version="1",
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
        ),
    )


def test_semantic_planning_reuses_an_existing_mask_without_inference():
    service = FakeSemanticService()
    base = recipe().model_copy(update={"masks": (_semantic_mask(),)})

    planning = plan_semantic_masks(
        ENVIRONMENTAL_PORTRAIT,
        report(scene=SceneLabel.PORTRAIT),
        base,
        image_id="image-1",
        service=service,
    )

    assert service.calls == []
    assert planning.recipe == base
    assert planning.mask_ids == ("mask_semantic_person",)


@pytest.mark.parametrize("code", ["semantic_mask_unavailable", "semantic_mask_timeout"])
def test_semantic_planning_degrades_to_global_when_inference_fails(code: str):
    service = FakeSemanticService(error=AppError(503, code, "no matte"))

    planning = plan_semantic_masks(
        ENVIRONMENTAL_PORTRAIT,
        report(scene=SceneLabel.PORTRAIT),
        recipe(),
        image_id="image-1",
        service=service,
    )

    assert planning.recipe.masks == ()
    assert planning.mask_ids == ()
    assert any("退化为全局" in item for item in planning.limitations)


def test_semantic_planning_degrades_without_a_service():
    planning = plan_semantic_masks(
        ENVIRONMENTAL_PORTRAIT,
        report(scene=SceneLabel.PORTRAIT),
        recipe(),
        image_id="image-1",
        service=None,
    )

    assert planning.recipe.masks == ()
    assert any("未配置" in item for item in planning.limitations)


def test_semantic_local_intent_is_mode_bounded_and_continuous():
    assert semantic_local_intent("person", 0.0, ConversionMode.STYLE) == {}
    totals = {
        mode: sum(abs(value) for value in semantic_local_intent("person", 0.8, mode).values())
        for mode in _MODES
    }

    assert totals[ConversionMode.NATURAL] < totals[ConversionMode.STYLE]
    assert totals[ConversionMode.STYLE] < totals[ConversionMode.CREATIVE]
    assert set(semantic_local_intent("sky", 0.8, ConversionMode.STYLE)) <= {
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
    }


def test_mock_planner_uses_only_the_prepared_semantic_mask():
    analysis = report(scene=SceneLabel.PORTRAIT)
    base = recipe().model_copy(update={"masks": (_semantic_mask(),)})
    context = build_style_context(
        ENVIRONMENTAL_PORTRAIT,
        analysis,
        mode=ConversionMode.STYLE,
        strength=0.6,
        image_id="image-1",
        image_sha256="e" * 64,
    )
    request = PlannerRequest(
        analysis=analysis,
        recipe=base,
        preferences=_PREFS,
        mode=PlannerMode.STYLE,
        style=ENVIRONMENTAL_PORTRAIT.to_style_definition(),
        style_strength=0.6,
        style_context=context,
    )

    draft = MockPlannerProvider().plan(request)
    generated = generate_recipe(
        base,
        analysis,
        draft,
        _PREFS,
        request.style,
        0.6,
        conversion_mode=ConversionMode.STYLE,
        dynamic_style=True,
    )

    assert len(draft.local_adjustments) == 1
    assert draft.local_adjustments[0].mask_id == "mask_semantic_person"
    assert generated.recipe.masks == base.masks
    assert {item.mask_id for item in generated.recipe.local_adjustments} == {"mask_semantic_person"}


def test_validator_rejects_a_local_adjustment_on_an_unprepared_mask():
    current = recipe()
    proposed = current.model_copy(
        update={
            "local_adjustments": (
                LocalAdjustment(
                    id="local_ai_1",
                    mask_id="mask_semantic_person",
                    adjustments=LocalAdjustments(exposure_ev=0.1),
                ),
            )
        }
    )

    with pytest.raises(RecipeValidationError, match="unknown maskId"):
        validate_recipe(proposed, current=current)
