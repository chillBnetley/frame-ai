from __future__ import annotations

from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from app.imaging.color_grading import apply_color_grading
from app.imaging.color_ops import apply_color
from app.imaging.curves import apply_curves
from app.imaging.geometry import inscribed_scale
from app.imaging.hsl import apply_hsl
from app.imaging.loader import load_image
from app.imaging.output import to_uint8
from app.imaging.params_map import DRAFT_MAX_EDGE, FINAL_MAX_EDGE
from app.imaging.pipeline import render, tier_max_edge
from app.imaging.tone import (
    apply_contrast,
    apply_tone_linear,
    linear_to_srgb,
    srgb_to_linear,
)
from app.models.recipe import (
    Adjustments,
    ColorGradeZone,
    ColorGrading,
    Crop,
    CurvePoint,
    CurveSet,
    HslAdjustments,
    HslBand,
    LocalAdjustment,
    LocalAdjustments,
    UserMask,
)
from tests.golden_support import source_bytes

SHA_A = "a" * 64
SHA_B = "b" * 64


def _png_bytes(pixels: np.ndarray) -> bytes:
    buffer = BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def _synthetic_photo(width: int, height: int) -> np.ndarray:
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u = x / max(width - 1, 1)
    v = y / max(height - 1, 1)
    red = 0.1 + 0.7 * u
    green = 0.15 + 0.55 * v
    blue = 0.25 + 0.4 * (1.0 - u) + 0.15 * np.sin(3.0 * np.pi * u) * np.cos(2.0 * np.pi * v)
    blob = np.clip(1.0 - np.sqrt((u - 0.55) ** 2 + (v - 0.5) ** 2) / 0.35, 0.0, 1.0)
    blob = blob * blob * (3.0 - 2.0 * blob)
    red = np.clip(red + 0.2 * blob, 0.0, 1.0)
    blue = np.clip(blue - 0.05 * blob, 0.0, 1.0)
    data = np.stack([red, green, blue], axis=-1)
    return np.rint(data * 255.0).astype(np.uint8)


def _load_pixels(pixels: np.ndarray):
    return load_image(_png_bytes(pixels))


def test_neutral_recipe_is_an_identity_render():
    payload = source_bytes("ramp")
    loaded = load_image(payload)

    rendered = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")

    assert rendered.rgb.dtype == np.uint8
    assert (rendered.width, rendered.height) == (loaded.width, loaded.height)
    difference = np.abs(
        rendered.rgb.astype(np.int16) - np.rint(loaded.rgb * 255.0).astype(np.int16)
    )
    assert int(difference.max()) <= 1


def test_render_tiers_and_explicit_edges():
    assert tier_max_edge("draft") == DRAFT_MAX_EDGE
    assert tier_max_edge("final") == FINAL_MAX_EDGE
    assert tier_max_edge("export") is None

    loaded = _load_pixels(_synthetic_photo(1280, 640))
    adjustments = Adjustments(contrast=10)

    draft = render(loaded, adjustments, image_sha256=SHA_A, quality="draft")
    final = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    exported = render(loaded, adjustments, image_sha256=SHA_A, quality="export")
    resized = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=400,
    )

    assert (draft.width, draft.height) == (960, 480)
    assert (final.width, final.height) == (1280, 640)
    assert (exported.width, exported.height) == (1280, 640)
    assert (resized.width, resized.height) == (400, 200)


def test_large_export_denoise_reports_a_warning():
    loaded = _load_pixels(_synthetic_photo(64, 48))

    simplified = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=1,
    )
    below_threshold = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=64 * 48,
    )
    preview = render(
        loaded,
        Adjustments(denoise=50),
        image_sha256=SHA_A,
        quality="final",
        denoise_simplify_pixels=1,
    )
    without_denoise = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        quality="export",
        denoise_simplify_pixels=1,
    )

    assert simplified.warnings == ("denoise_simplified",)
    assert below_threshold.warnings == ()
    assert preview.warnings == ()
    assert without_denoise.warnings == ()


def test_rotation_and_crop_report_the_rotated_canvas():
    loaded = _load_pixels(_synthetic_photo(200, 120))

    rotated = render(
        loaded,
        Adjustments(rotation_deg=7.5),
        image_sha256=SHA_A,
        quality="export",
    )
    cropped = render(
        loaded,
        Adjustments(rotation_deg=7.5, crop=Crop(x=0.1, y=0.1, w=0.6, h=0.6)),
        image_sha256=SHA_A,
        quality="export",
    )
    unrotated = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")

    expected_width = max(1, round(loaded.width * inscribed_scale(200, 120, 7.5)))
    expected_height = max(1, round(loaded.height * inscribed_scale(200, 120, 7.5)))
    assert abs(rotated.canvas_width - expected_width) <= 1
    assert abs(rotated.canvas_height - expected_height) <= 1
    assert (rotated.width, rotated.height) == (rotated.canvas_width, rotated.canvas_height)
    assert cropped.canvas_width == rotated.canvas_width
    assert cropped.canvas_height == rotated.canvas_height
    assert cropped.width < rotated.width
    assert cropped.height < rotated.height
    assert (unrotated.canvas_width, unrotated.canvas_height) == (200, 120)


def test_full_frame_crop_matches_no_crop():
    loaded = _load_pixels(_synthetic_photo(120, 80))

    without = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    with_crop = render(
        loaded,
        Adjustments(crop=Crop(x=0.0, y=0.0, w=1.0, h=1.0)),
        image_sha256=SHA_A,
        quality="export",
    )

    assert np.array_equal(without.rgb, with_crop.rgb)


def test_whites_and_blacks_affect_the_expected_ends_on_a_standard_ramp():
    width, height = 256, 32
    row = np.rint(np.linspace(0.0, 255.0, width)).astype(np.uint8)
    gray = np.repeat(row[None, :, None], height, axis=0)
    loaded = _load_pixels(np.repeat(gray, 3, axis=2))
    quarter = width // 4

    def left_edge(result) -> float:
        return float(result.rgb[:, :quarter].mean())

    def right_edge(result) -> float:
        return float(result.rgb[:, -quarter:].mean())

    neutral = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    # Lightroom convention: positive Blacks darkens the shadow end, negative lifts it.
    darker_blacks = render(loaded, Adjustments(blacks=100), image_sha256=SHA_A, quality="export")
    lifted_blacks = render(loaded, Adjustments(blacks=-100), image_sha256=SHA_A, quality="export")
    brighter_whites = render(loaded, Adjustments(whites=100), image_sha256=SHA_A, quality="export")
    darker_whites = render(loaded, Adjustments(whites=-100), image_sha256=SHA_A, quality="export")

    assert left_edge(darker_blacks) < left_edge(neutral) - 1.0
    assert right_edge(darker_blacks) == pytest.approx(right_edge(neutral), abs=1.0)
    assert left_edge(lifted_blacks) > left_edge(neutral) + 1.0
    assert right_edge(lifted_blacks) == pytest.approx(right_edge(neutral), abs=1.0)

    assert right_edge(brighter_whites) > right_edge(neutral) + 1.0
    assert left_edge(brighter_whites) == pytest.approx(left_edge(neutral), abs=1.0)
    assert right_edge(darker_whites) < right_edge(neutral) - 1.0
    assert left_edge(darker_whites) == pytest.approx(left_edge(neutral), abs=1.0)

    for result in (lifted_blacks, darker_blacks, brighter_whites, darker_whites):
        assert np.array_equal(result.rgb[..., 0], result.rgb[..., 1])
        assert np.array_equal(result.rgb[..., 1], result.rgb[..., 2])


def test_render_is_byte_for_byte_deterministic():
    pixels = _synthetic_photo(320, 240)
    adjustments = Adjustments(
        exposure_ev=0.25,
        contrast=10,
        highlights=-15,
        shadows=20,
        whites=12,
        blacks=-8,
        temperature=8,
        saturation=10,
        clarity=25,
        vignette=15,
        denoise=20,
        sharpen=20,
        grain=30,
    )

    first = render(_load_pixels(pixels), adjustments, image_sha256=SHA_A, quality="final")
    second = render(_load_pixels(pixels), adjustments, image_sha256=SHA_A, quality="final")

    assert first.rgb.tobytes() == second.rgb.tobytes()


def test_grain_pattern_only_depends_on_the_original_digest():
    loaded = _load_pixels(_synthetic_photo(160, 120))
    adjustments = Adjustments(grain=40)

    first = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    same = render(loaded, adjustments, image_sha256=SHA_A, quality="final")
    other = render(loaded, adjustments, image_sha256=SHA_B, quality="final")

    assert np.array_equal(first.rgb, same.rgb)
    assert not np.array_equal(first.rgb, other.rgb)


def test_resolution_invariance_stays_within_three_gray_levels():
    high_pixels = _synthetic_photo(1600, 1200)
    low_pixels = cv2.resize(high_pixels, (800, 600), interpolation=cv2.INTER_AREA)
    adjustments = Adjustments(
        exposure_ev=0.25,
        temperature=12,
        tint=-8,
        highlights=30,
        shadows=25,
        contrast=18,
        saturation=12,
        vibrance=30,
        clarity=30,
        vignette=20,
        sharpen=25,
    )

    high = render(
        _load_pixels(high_pixels),
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=1600,
    )
    low = render(
        _load_pixels(low_pixels),
        adjustments,
        image_sha256=SHA_A,
        quality="export",
        max_edge=800,
    )
    downscaled = cv2.resize(
        high.rgb,
        (low.width, low.height),
        interpolation=cv2.INTER_AREA,
    )

    mean_difference = float(
        np.abs(downscaled.astype(np.float32) - low.rgb.astype(np.float32)).mean()
    )
    assert mean_difference <= 3.0


def _curve(*pairs: tuple[float, float]) -> tuple[CurvePoint, ...]:
    return tuple(CurvePoint(x=x, y=y) for x, y in pairs)


def test_empty_curves_are_an_identity_render():
    loaded = _load_pixels(_synthetic_photo(64, 48))

    without = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    with_empty = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        curve=CurveSet(),
        quality="export",
    )

    assert np.array_equal(without.rgb, with_empty.rgb)


def test_curves_change_rendering_and_channel_curves_stay_isolated():
    loaded = _load_pixels(_synthetic_photo(96, 64))
    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")

    master = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        curve=CurveSet(master=_curve((0, 0), (0.5, 0.65), (1, 1))),
        quality="export",
    )
    red_only = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        curve=CurveSet(red=_curve((0, 0), (0.5, 0.7), (1, 1))),
        quality="export",
    )

    assert not np.array_equal(master.rgb, base.rgb)
    assert not np.array_equal(red_only.rgb[..., 0], base.rgb[..., 0])
    assert np.array_equal(red_only.rgb[..., 1], base.rgb[..., 1])
    assert np.array_equal(red_only.rgb[..., 2], base.rgb[..., 2])


def test_curves_run_after_contrast_and_before_saturation():
    loaded = _load_pixels(_synthetic_photo(80, 64))
    adjustments = Adjustments(contrast=25, saturation=40, vibrance=20)
    curve = CurveSet(master=_curve((0, 0.05), (0.5, 0.6), (1, 0.95)))

    rendered = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        curve=curve,
        quality="export",
    )

    expected = linear_to_srgb(srgb_to_linear(loaded.rgb))
    expected = apply_contrast(expected, adjustments.contrast)
    expected = apply_curves(expected, curve)
    expected = apply_color(
        expected,
        saturation=adjustments.saturation,
        vibrance=adjustments.vibrance,
    )

    assert np.array_equal(rendered.rgb, to_uint8(expected))


def test_black_and_white_land_on_the_curve_not_on_the_contrast():
    """Order proof that needs no reference pipeline.

    Contrast has fixed points at 0, 0.5 and 1, so black and white leave it
    untouched and must sit on the curve's own endpoints: 0.25 -> 64, 0.8 -> 204.
    Running the curve first would contrast those values to smoothstep(0.25) =
    0.15625 (40) and smoothstep(0.8) = 0.896 (228).
    """
    pixels = np.zeros((2, 6, 3), dtype=np.uint8)
    pixels[1] = 255
    loaded = _load_pixels(pixels)
    curve = CurveSet(master=_curve((0.0, 0.25), (0.5, 0.5), (1.0, 0.8)))

    rendered = render(
        loaded,
        Adjustments(contrast=100, saturation=100),
        image_sha256=SHA_A,
        curve=curve,
        quality="export",
    )

    assert np.unique(rendered.rgb[0]).tolist() == [64]
    assert np.unique(rendered.rgb[1]).tolist() == [204]


def test_desaturating_reads_the_curved_channels():
    """A curve that pins 0 and 1 leaves each primary alone, so desaturating it
    afterwards must return exactly that primary's Rec.709 luma. Desaturating
    first and curving second lands the red primary near 12 and the blue near 4.
    """
    pixels = np.array([[[255, 0, 0], [0, 255, 0], [0, 0, 255]]], dtype=np.uint8)
    loaded = _load_pixels(pixels)
    curve = CurveSet(master=_curve((0.0, 0.0), (0.5, 0.1), (1.0, 1.0)))

    rendered = render(
        loaded,
        Adjustments(saturation=-100),
        image_sha256=SHA_A,
        curve=curve,
        quality="export",
    )

    greys = rendered.rgb.reshape(-1, 3)
    assert np.all(greys == greys[:, :1])
    assert greys[:, 0].tolist() == [54, 182, 18]


def test_empty_hsl_is_an_identity_render():
    loaded = _load_pixels(_synthetic_photo(64, 48))

    without = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    with_empty = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        hsl=HslAdjustments(),
        quality="export",
    )

    assert np.array_equal(without.rgb, with_empty.rgb)


def test_hsl_changes_rendering():
    loaded = _load_pixels(_synthetic_photo(96, 64))
    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    shifted = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        hsl=HslAdjustments(blue=HslBand(hue=30, saturation=25)),
        quality="export",
    )

    assert not np.array_equal(shifted.rgb, base.rgb)


def test_hsl_runs_after_curves_and_before_saturation():
    loaded = _load_pixels(_synthetic_photo(80, 64))
    adjustments = Adjustments(contrast=20, saturation=30, vibrance=15)
    curve = CurveSet(master=_curve((0, 0.04), (0.5, 0.55), (1, 0.96)))
    hsl = HslAdjustments(
        red=HslBand(hue=20, saturation=15),
        blue=HslBand(hue=-25, luminance=10),
    )

    rendered = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        curve=curve,
        hsl=hsl,
        quality="export",
    )

    expected = linear_to_srgb(srgb_to_linear(loaded.rgb))
    expected = apply_contrast(expected, adjustments.contrast)
    expected = apply_curves(expected, curve)
    expected = apply_hsl(expected, hsl)
    expected = apply_color(
        expected,
        saturation=adjustments.saturation,
        vibrance=adjustments.vibrance,
    )

    assert np.array_equal(rendered.rgb, to_uint8(expected))


def test_empty_color_grading_is_an_identity_render():
    loaded = _load_pixels(_synthetic_photo(64, 48))

    without = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    with_empty = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        color_grading=ColorGrading(),
        quality="export",
    )

    assert np.array_equal(without.rgb, with_empty.rgb)


def test_color_grading_changes_rendering():
    loaded = _load_pixels(_synthetic_photo(96, 64))
    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    graded = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        color_grading=ColorGrading(
            shadows=ColorGradeZone(hue=220, saturation=30),
            highlights=ColorGradeZone(hue=45, saturation=25),
        ),
        quality="export",
    )

    assert not np.array_equal(graded.rgb, base.rgb)


def test_color_grading_runs_after_saturation_and_before_local_adjustments():
    loaded = _load_pixels(_synthetic_photo(80, 64))
    adjustments = Adjustments(saturation=30, vibrance=15)
    grading = ColorGrading(
        shadows=ColorGradeZone(hue=200, saturation=25),
        highlights=ColorGradeZone(hue=50, saturation=20),
        balance=5,
        blending=55,
    )

    rendered = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        color_grading=grading,
        quality="export",
    )

    expected = linear_to_srgb(srgb_to_linear(loaded.rgb))
    expected = apply_contrast(expected, adjustments.contrast)
    expected = apply_color(
        expected,
        saturation=adjustments.saturation,
        vibrance=adjustments.vibrance,
    )
    expected = apply_color_grading(expected, grading)

    assert np.array_equal(rendered.rgb, to_uint8(expected))


def test_render_rejects_invalid_max_edge():
    loaded = _load_pixels(_synthetic_photo(32, 24))

    with pytest.raises(ValueError):
        render(loaded, Adjustments(), image_sha256=SHA_A, max_edge=0)


def test_local_adjustment_only_changes_pixels_inside_the_mask():
    loaded = _load_pixels(_synthetic_photo(160, 120))
    mask = UserMask(
        id="mask_center",
        x=0.25,
        y=0.25,
        width=0.5,
        height=0.5,
        feather=0.0,
    )
    local = LocalAdjustment(
        id="local_1",
        mask_id="mask_center",
        adjustments=LocalAdjustments(exposure_ev=1.0),
    )

    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    adjusted = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        masks=(mask,),
        local_adjustments=(local,),
        quality="export",
    )

    assert not np.array_equal(adjusted.rgb[60, 80], base.rgb[60, 80])
    assert np.array_equal(adjusted.rgb[:20, :], base.rgb[:20, :])
    assert np.array_equal(adjusted.rgb[:, :20], base.rgb[:, :20])
    assert np.array_equal(adjusted.rgb[-20:, :], base.rgb[-20:, :])
    assert np.array_equal(adjusted.rgb[:, -20:], base.rgb[:, -20:])


def test_full_mask_local_exposure_matches_global_exposure():
    loaded = _load_pixels(_synthetic_photo(80, 64))
    local = LocalAdjustment(
        id="local_1",
        adjustments=LocalAdjustments(exposure_ev=0.5),
    )

    local_render = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        local_adjustments=(local,),
        quality="export",
    )
    global_render = render(
        loaded,
        Adjustments(exposure_ev=0.5),
        image_sha256=SHA_A,
        quality="export",
    )

    difference = np.abs(local_render.rgb.astype(np.int16) - global_render.rgb.astype(np.int16))
    assert int(difference.max()) <= 1


def test_disabled_or_empty_local_adjustments_are_identity():
    loaded = _load_pixels(_synthetic_photo(64, 48))
    mask = UserMask(
        id="mask_center",
        x=0.2,
        y=0.2,
        width=0.6,
        height=0.6,
        feather=10,
    )
    zero = LocalAdjustment(id="local_zero", mask_id="mask_center")
    disabled = LocalAdjustment(
        id="local_disabled",
        enabled=False,
        adjustments=LocalAdjustments(exposure_ev=2.0, saturation=50),
    )

    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    rendered = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        masks=(mask,),
        local_adjustments=(zero, disabled),
        quality="export",
    )

    assert np.array_equal(rendered.rgb, base.rgb)
    assert rendered.warnings == ()


def test_multiple_masks_adjust_only_their_own_regions():
    loaded = _load_pixels(_synthetic_photo(200, 120))
    left = UserMask(
        id="mask_left",
        x=0.0,
        y=0.0,
        width=0.3,
        height=1.0,
        feather=0.0,
    )
    right = UserMask(
        id="mask_right",
        x=0.7,
        y=0.0,
        width=0.3,
        height=1.0,
        feather=0.0,
    )
    locals_ = (
        LocalAdjustment(
            id="local_b",
            mask_id="mask_left",
            adjustments=LocalAdjustments(exposure_ev=1.0),
        ),
        LocalAdjustment(
            id="local_a",
            mask_id="mask_right",
            adjustments=LocalAdjustments(exposure_ev=-1.0),
        ),
    )

    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    adjusted = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        masks=(left, right),
        local_adjustments=locals_,
        quality="export",
    )

    assert adjusted.rgb[:, :40].mean() > base.rgb[:, :40].mean() + 10
    assert adjusted.rgb[:, -40:].mean() < base.rgb[:, -40:].mean() - 10
    assert np.array_equal(adjusted.rgb[:, 80:120], base.rgb[:, 80:120])


def test_missing_mask_is_skipped_with_a_warning():
    loaded = _load_pixels(_synthetic_photo(64, 48))
    local = LocalAdjustment(
        id="local_1",
        mask_id="mask_missing",
        adjustments=LocalAdjustments(exposure_ev=1.0),
    )

    base = render(loaded, Adjustments(), image_sha256=SHA_A, quality="export")
    rendered = render(
        loaded,
        Adjustments(),
        image_sha256=SHA_A,
        local_adjustments=(local,),
        quality="export",
    )

    assert rendered.warnings == ("local_mask_missing:mask_missing",)
    assert np.array_equal(rendered.rgb, base.rgb)


def test_mask_outside_the_crop_has_no_effect():
    loaded = _load_pixels(_synthetic_photo(120, 80))
    mask = UserMask(
        id="mask_corner",
        x=0.0,
        y=0.0,
        width=0.1,
        height=0.1,
        feather=0.0,
    )
    local = LocalAdjustment(
        id="local_1",
        mask_id="mask_corner",
        adjustments=LocalAdjustments(exposure_ev=1.5),
    )
    adjustments = Adjustments(crop=Crop(x=0.5, y=0.5, w=0.5, h=0.5))

    base = render(loaded, adjustments, image_sha256=SHA_A, quality="export")
    rendered = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        masks=(mask,),
        local_adjustments=(local,),
        quality="export",
    )

    assert np.array_equal(rendered.rgb, base.rgb)
    assert rendered.warnings == ()


def test_local_mask_tracks_rotation_and_crop():
    loaded = _load_pixels(_synthetic_photo(240, 160))
    mask = UserMask(
        id="mask_center",
        x=0.45,
        y=0.45,
        width=0.1,
        height=0.1,
        feather=0.0,
    )
    local = LocalAdjustment(
        id="local_1",
        mask_id="mask_center",
        adjustments=LocalAdjustments(exposure_ev=1.5),
    )
    adjustments = Adjustments(
        rotation_deg=15.0,
        crop=Crop(x=0.2, y=0.2, w=0.6, h=0.6),
    )

    base = render(loaded, adjustments, image_sha256=SHA_A, quality="export")
    adjusted = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        masks=(mask,),
        local_adjustments=(local,),
        quality="export",
    )

    center_y = adjusted.height // 2
    center_x = adjusted.width // 2
    assert not np.array_equal(adjusted.rgb[center_y, center_x], base.rgb[center_y, center_x])
    assert np.array_equal(adjusted.rgb[:8, :8], base.rgb[:8, :8])
    assert np.array_equal(adjusted.rgb[-8:, -8:], base.rgb[-8:, -8:])


def test_local_adjustments_run_after_global_tone():
    loaded = _load_pixels(_synthetic_photo(96, 72))
    adjustments = Adjustments(exposure_ev=0.4)
    local = LocalAdjustment(
        id="local_1",
        adjustments=LocalAdjustments(contrast=35),
    )

    rendered = render(
        loaded,
        adjustments,
        image_sha256=SHA_A,
        local_adjustments=(local,),
        quality="export",
    )

    expected = apply_tone_linear(
        srgb_to_linear(loaded.rgb),
        exposure_ev=adjustments.exposure_ev,
        temperature=adjustments.temperature,
        tint=adjustments.tint,
        highlights=adjustments.highlights,
        shadows=adjustments.shadows,
    )
    expected = linear_to_srgb(expected, inplace=True)
    expected = apply_contrast(expected, 35)

    difference = np.abs(rendered.rgb.astype(np.int16) - to_uint8(expected).astype(np.int16))
    assert int(difference.max()) <= 1
