from __future__ import annotations

import numpy as np

from app.imaging.local_masks import apply_local_adjustments, mask_weights
from app.models.recipe import EditRecipe, LocalAdjustment, UserMask

WIDTH = 40
HEIGHT = 30


def _base() -> np.ndarray:
    column = np.linspace(0.1, 0.9, WIDTH, dtype=np.float32)[None, :, None]
    return np.ascontiguousarray(np.broadcast_to(column, (HEIGHT, WIDTH, 3)).copy())


def _mask() -> UserMask:
    return UserMask(id="mask_a", x=0.1, y=0.1, width=0.6, height=0.6, feather=0, opacity=100)


def _apply(recipe: EditRecipe) -> np.ndarray:
    rgb, _ = apply_local_adjustments(
        _base(),
        recipe.local_adjustments,
        recipe.masks,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    return rgb


def _local(**overrides: object) -> LocalAdjustment:
    payload: dict[str, object] = {
        "id": "local_a",
        "maskId": "full",
        "adjustments": {"exposureEv": 0.5},
    }
    payload.update(overrides)
    return LocalAdjustment.model_validate(payload)


def test_masked_opacity_multiplies_the_mask_weight():
    mask = _mask()
    masked = EditRecipe(
        masks=(mask,),
        local_adjustments=(_local(maskId=mask.id, opacity=50.0, adjustments={"exposureEv": 1.0}),),
    )
    reference_full = EditRecipe(
        masks=(mask,),
        local_adjustments=(_local(maskId=mask.id, adjustments={"exposureEv": 1.0}),),
    )

    base = _base()
    adjusted = _apply(reference_full)
    weights = mask_weights(
        mask,
        output_width=WIDTH,
        output_height=HEIGHT,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    expected = np.clip(
        base + (adjusted - base) * (weights[..., None] * 0.5),
        0.0,
        1.0,
    ).astype(np.float32)

    np.testing.assert_allclose(_apply(masked), expected, atol=1e-6)


def test_legacy_normal_masked_layer_keeps_the_original_formula():
    mask = _mask()
    legacy = EditRecipe(
        masks=(mask,),
        local_adjustments=(_local(maskId=mask.id),),
    )
    full = EditRecipe(local_adjustments=(_local(),))

    base = _base()
    adjusted = _apply(full)
    weights = mask_weights(
        mask,
        output_width=WIDTH,
        output_height=HEIGHT,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    expected = np.clip(base + (adjusted - base) * weights[..., None], 0.0, 1.0)

    np.testing.assert_array_equal(_apply(legacy), expected.astype(np.float32))


def test_swapping_order_changes_the_composite():
    first = _local(id="local_a", order=0, blendMode="multiply", adjustments={"exposureEv": 0.5})
    second = _local(id="local_b", order=1, adjustments={"exposureEv": -0.5})
    original = EditRecipe(local_adjustments=(first, second))
    swapped = EditRecipe(
        local_adjustments=(
            first.model_copy(update={"order": 1}),
            second.model_copy(update={"order": 0}),
        )
    )

    forward = _apply(original)
    reverse = _apply(swapped)

    assert not np.array_equal(forward, reverse)


def test_disabled_or_zero_opacity_layers_are_skipped():
    base = _base()
    disabled = EditRecipe(
        local_adjustments=(
            _local(enabled=False, blendMode="multiply", adjustments={"exposureEv": 2.0}),
        )
    )
    transparent = EditRecipe(
        local_adjustments=(
            _local(opacity=0.0, blendMode="overlay", adjustments={"exposureEv": 2.0}),
        )
    )

    np.testing.assert_array_equal(_apply(disabled), base)
    np.testing.assert_array_equal(_apply(transparent), base)


def test_blend_modes_stay_in_range():
    for mode in ("normal", "multiply", "screen", "overlay"):
        recipe = EditRecipe(
            local_adjustments=(
                _local(blendMode=mode, opacity=75.0, adjustments={"exposureEv": 2.5}),
            )
        )
        output = _apply(recipe)
        assert output.dtype == np.float32
        assert np.isfinite(output).all()
        assert output.min() >= 0.0
        assert output.max() <= 1.0


def test_masked_non_normal_layer_multiplies_mask_weight_and_blend():
    mask = _mask()
    adjustments = {"exposureEv": 0.8}
    masked = EditRecipe(
        masks=(mask,),
        local_adjustments=(
            _local(
                maskId=mask.id,
                blendMode="multiply",
                opacity=60.0,
                adjustments=adjustments,
            ),
        ),
    )
    reference = EditRecipe(local_adjustments=(_local(adjustments=adjustments),))

    base = _base()
    adjusted = _apply(reference)
    weights = mask_weights(
        mask,
        output_width=WIDTH,
        output_height=HEIGHT,
        source_width=WIDTH,
        source_height=HEIGHT,
        rotation_deg=0.0,
        crop=None,
    )
    blended = base * np.clip(adjusted, 0.0, 1.0)
    expected = np.clip(
        base + (blended - base) * (weights[..., None] * 0.6),
        0.0,
        1.0,
    ).astype(np.float32)

    np.testing.assert_allclose(_apply(masked), expected, atol=1e-6)
