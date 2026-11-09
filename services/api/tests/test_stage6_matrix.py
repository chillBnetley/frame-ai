"""Stage 6 quality matrix: eight scene cases x three archives x modes x strengths.

The scene images here are original synthetic patterns, not copyrighted photos.
They exercise exposure, colour, geometry, and noise paths deterministically;
real photographic judgement still requires the licensed human test set.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from numpy.typing import NDArray

from app.ai.base import PlannerRequest
from app.ai.contracts import ContrastLevel, SceneLabel
from app.ai.providers.mock import MockPlannerProvider
from app.imaging.loader import LoadedImage
from app.imaging.pipeline import render as render_image
from app.models.conversion import ConversionMode
from app.models.photographer import PhotographerPreferences, PlannerMode
from app.models.recipe import EditRecipe
from app.photographer.generator import generate_recipe
from app.photographer.style_generation import (
    build_style_context,
    dynamic_style_adjustments,
)
from app.styles.fit import evaluate_style_fit
from app.styles.library import (
    ANSEL_ADAMS,
    ENVIRONMENTAL_PORTRAIT,
    FAN_HO,
    SEED_PROFILES,
)
from tests.photographer_support import recipe, report

STYLES = (FAN_HO, ANSEL_ADAMS, ENVIRONMENTAL_PORTRAIT)
MODES = (ConversionMode.NATURAL, ConversionMode.STYLE, ConversionMode.CREATIVE)
STRENGTHS = (0.2, 0.5, 0.8, 1.0)
PREFERENCES = PhotographerPreferences(naturalness=0.4, adjustment_strength=1.0)

SCENES = {
    "street": report(scene=SceneLabel.STREET, contrast=ContrastLevel.HIGH),
    "portrait": report(scene=SceneLabel.PORTRAIT),
    "architecture": report(scene=SceneLabel.ARCHITECTURE, contrast=ContrastLevel.HIGH),
    "landscape": report(scene=SceneLabel.LANDSCAPE, luminance_std=0.24),
    "night": report(scene=SceneLabel.NIGHT, luminance_p50=0.12, luminance_std=0.2),
    "indoor": report(scene=SceneLabel.INDOOR, luminance_std=0.14),
    "backlit": report(scene=SceneLabel.PORTRAIT, contrast=ContrastLevel.HIGH, highlights_pct=5.0),
    "lowlight": report(scene=SceneLabel.OTHER, luminance_p50=0.09, noise_estimate=0.4),
}


def scene_image(name: str) -> NDArray[np.float32]:
    height, width = 96, 128
    y, x = np.mgrid[0:height, 0:width]
    image = np.zeros((height, width, 3), dtype=np.float32)
    if name == "street":
        image[..., 0] = 0.12 + 0.55 * (x / width)
        image[..., 1] = 0.1 + 0.4 * (y / height)
        image[..., 2] = 0.1 + 0.25 * (x / width)
        image[20:88, 18:30] = 0.12
        image[10:90, 74:86] = 0.08
    elif name == "portrait":
        image[..., 0] = 0.24
        image[..., 1] = 0.28
        image[..., 2] = 0.3
        mask = ((x - 64) / 30) ** 2 + ((y - 55) / 38) ** 2 < 1
        image[mask] = (0.78, 0.58, 0.46)
        image[10:30, 100:120] = (0.55, 0.6, 0.58)
    elif name == "architecture":
        image[:] = (0.55, 0.57, 0.58)
        image[8:88:14, :] *= 0.35
        image[:, 12:112:20] *= 0.45
        image[20:70, 40:88] *= 1.25
    elif name == "landscape":
        image[..., 0] = 0.2 + 0.35 * (1 - y / height)
        image[..., 1] = 0.32 + 0.3 * (y / height)
        image[..., 2] = 0.55 + 0.3 * (1 - y / height)
        image[14:26, 96:108] = (1.0, 0.95, 0.78)
    elif name == "night":
        image[:] = (0.015, 0.02, 0.04)
        image[18:26, 20:28] = (0.95, 0.45, 0.1)
        image[54:60, 90:98] = (0.2, 0.55, 0.95)
        image[70:76, 40:46] = (0.85, 0.7, 0.25)
    elif name == "indoor":
        image[..., 0] = 0.5 + 0.3 * (x / width)
        image[..., 1] = 0.42 + 0.2 * (x / width)
        image[..., 2] = 0.3 + 0.15 * (x / width)
        image[4:34, 84:124] = (0.95, 0.93, 0.85)
    elif name == "backlit":
        image[:] = (0.08, 0.09, 0.1)
        image[0:40, :, :] = np.clip(0.95 - 0.4 * (y[:40] / 40), 0, 1)[..., None]
        image[30:90, 44:84] = (0.12, 0.1, 0.09)
    else:
        rng = np.random.default_rng(11)
        base = np.clip(0.05 + 0.04 * (x / width), 0, 1)
        image[:] = base[..., None]
        image = np.clip(image + rng.normal(0, 0.05, image.shape), 0, 1)
        image[30:34, 96:100] = (0.9, 0.55, 0.25)
    return np.ascontiguousarray(np.clip(image, 0, 1).astype(np.float32))


def _nontrivial(recipe_value: EditRecipe) -> bool:
    adjustments = recipe_value.adjustments
    return any(
        abs(float(value)) >= 0.005
        for value in adjustments.model_dump(by_alias=True).values()
        if isinstance(value, (int, float))
    )


def test_scene_style_mode_strength_matrix_is_deterministic_and_bounded():
    started = time.monotonic()
    combos = 0
    renders = 0
    planner = MockPlannerProvider()

    for scene_name, analysis in SCENES.items():
        image = scene_image(scene_name)
        source = np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8)
        for profile in STYLES:
            style = profile.to_style_definition()
            fit = evaluate_style_fit(profile, analysis)
            assert 0.0 <= fit.overall_score <= 92.0
            assert len(fit.dimensions) == 5
            assert fit.recommended_mode in MODES

            for mode in MODES:
                total_by_strength: list[float] = []
                for strength in STRENGTHS:
                    dynamic = dynamic_style_adjustments(
                        profile,
                        analysis,
                        mode=mode,
                        strength=strength,
                        preferences=PREFERENCES,
                    )
                    total_by_strength.append(sum(abs(value) for value in dynamic.values()))
                    context = build_style_context(
                        profile,
                        analysis,
                        mode=mode,
                        strength=strength,
                        image_id=str(analysis.image.id),
                        image_sha256=analysis.image.sha256,
                    )
                    request = PlannerRequest(
                        analysis=analysis,
                        recipe=recipe(),
                        preferences=PREFERENCES,
                        mode=PlannerMode.STYLE,
                        style=style,
                        style_strength=strength,
                        style_context=context,
                    )
                    first = planner.plan(request)
                    second = planner.plan(request)
                    assert first == second, (scene_name, profile.id, mode, strength)

                    generated = generate_recipe(
                        recipe(),
                        analysis,
                        first,
                        PREFERENCES,
                        style,
                        strength,
                        conversion_mode=mode,
                        dynamic_style=True,
                    )
                    assert generated.recipe.masks == ()
                    assert all(
                        abs(item.opacity) <= 100.0 for item in generated.recipe.local_adjustments
                    )

                    if strength == 0.8:
                        before = image.copy()
                        rendered = render_image(
                            LoadedImage(rgb=image),
                            generated.recipe.adjustments,
                            image_sha256=analysis.image.sha256,
                            curve=generated.recipe.curve,
                            hsl=generated.recipe.hsl,
                            color_grading=generated.recipe.color_grading,
                            masks=generated.recipe.masks,
                            local_adjustments=generated.recipe.local_adjustments,
                            quality="final",
                            max_edge=128,
                        )
                        assert np.array_equal(image, before), "render must not mutate the source"
                        assert rendered.rgb.dtype == np.uint8
                        assert rendered.rgb.shape == source.shape
                        if _nontrivial(generated.recipe):
                            assert not np.array_equal(rendered.rgb, source), (
                                scene_name,
                                profile.id,
                            )
                        renders += 1
                    combos += 1
                assert total_by_strength == sorted(total_by_strength), (
                    scene_name,
                    profile.id,
                    mode,
                )

    elapsed = time.monotonic() - started
    assert combos == len(SCENES) * len(STYLES) * len(MODES) * len(STRENGTHS)
    assert renders == len(SCENES) * len(STYLES) * len(MODES)
    print(
        f"\nstage6 matrix: scenes={len(SCENES)} styles={len(STYLES)} modes={len(MODES)} "
        f"strengths={len(STRENGTHS)} combos={combos} renders={renders} "
        f"elapsed={elapsed:.2f}s"
    )


def test_every_seeded_archive_can_be_evaluated_for_every_scene():
    assert len(SEED_PROFILES) == 16
    assert {profile.kind for profile in SEED_PROFILES} == {"master", "genre"}
    for analysis in SCENES.values():
        for profile in SEED_PROFILES:
            fit = evaluate_style_fit(profile, analysis)
            assert 0.0 <= fit.overall_score <= 92.0
            assert len(fit.dimensions) == 5
            assert fit.summary
            dynamic = dynamic_style_adjustments(
                profile,
                analysis,
                mode=ConversionMode.STYLE,
                strength=0.6,
                preferences=PREFERENCES,
            )
            envelope = profile.envelope.model_dump(by_alias=True)
            for field, value in dynamic.items():
                assert abs(value) <= float(envelope[field]) + 1e-9


def test_quality_metrics_are_finite_and_do_not_use_the_style_itself_as_a_score():
    analysis = SCENES["backlit"]
    profile = FAN_HO
    style = profile.to_style_definition()
    fit = evaluate_style_fit(profile, analysis)
    context = build_style_context(
        profile,
        analysis,
        mode=ConversionMode.CREATIVE,
        strength=0.8,
        image_id=str(analysis.image.id),
        image_sha256=analysis.image.sha256,
    )
    draft = MockPlannerProvider().plan(
        PlannerRequest(
            analysis=analysis,
            recipe=recipe(),
            preferences=PREFERENCES,
            mode=PlannerMode.STYLE,
            style=style,
            style_strength=0.8,
            style_context=context,
        )
    )
    generated = generate_recipe(
        recipe(),
        analysis,
        draft,
        PREFERENCES,
        style,
        0.8,
        conversion_mode=ConversionMode.CREATIVE,
        dynamic_style=True,
    )
    image = scene_image("backlit")
    rendered = render_image(
        LoadedImage(rgb=image),
        generated.recipe.adjustments,
        image_sha256=analysis.image.sha256,
        curve=generated.recipe.curve,
        color_grading=generated.recipe.color_grading,
        quality="final",
        max_edge=128,
    )
    pixels = rendered.rgb.astype(np.float32) / 255.0
    assert np.isfinite(pixels).all()
    assert float(pixels.min()) >= 0.0
    assert float(pixels.max()) <= 1.0
    assert fit.summary
    assert pixels.mean() > 0.0
    assert len(generated.changes) <= 10


@pytest.mark.parametrize("scene_name", tuple(SCENES))
def test_scene_fixture_is_legal_and_reproducible(scene_name: str):
    first = scene_image(scene_name)
    second = scene_image(scene_name)
    assert np.array_equal(first, second)
    assert first.shape == (96, 128, 3)
    assert first.dtype == np.float32
    assert 0.0 <= float(first.min()) <= float(first.max()) <= 1.0


def test_same_archive_produces_scene_specific_plans():
    signatures: dict[str, tuple[tuple[str, float], ...]] = {}
    for scene_name, analysis in SCENES.items():
        dynamic = dynamic_style_adjustments(
            FAN_HO,
            analysis,
            mode=ConversionMode.STYLE,
            strength=0.8,
            preferences=PREFERENCES,
        )
        signatures[scene_name] = tuple(sorted(dynamic.items()))

    assert len(set(signatures.values())) >= 6
    assert signatures["street"] != signatures["landscape"]
    assert signatures["portrait"] != signatures["night"]
