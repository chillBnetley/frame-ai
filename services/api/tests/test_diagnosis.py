from __future__ import annotations

import numpy as np
import pytest

from app.ai.contracts import (
    AnalysisOptions,
    IssueType,
    LightingDirection,
    Severity,
    SubjectRole,
    SubjectType,
    VisionResult,
)
from app.analysis.diagnosis import (
    HIGH_TEXTURE_LIMITATION,
    HORIZON_UNAVAILABLE_LIMITATION,
    DiagnosisContext,
    RegionSample,
    RegionSamples,
    build_candidates,
    sample_regions,
)
from app.analysis.regions import build_regions
from app.imaging.loader import LoadedImage
from tests.ai_support import analysis_options, measurement_summary, vision_payload

BASE_MEASUREMENTS: dict[str, object] = {
    "luminance_std": 0.18,
    "luminance_p1": 0.05,
    "luminance_p99": 0.98,
    "highlights_pct": 0.5,
    "shadows_pct": 0.5,
    "cast_temperature": 0.0,
    "cast_tint": 0.0,
    "sharpness": 0.30,
    "noise_estimate": 0.10,
    "horizon_tilt_deg": None,
}


def _vision(
    *,
    direction: LightingDirection = LightingDirection.SIDE,
    scene: str = "portrait",
    composition: dict[str, object] | None = None,
    bbox: dict[str, float] | None = None,
) -> dict[str, object]:
    payload = vision_payload()
    payload["lighting"] = {**payload["lighting"], "direction": direction.value}
    payload["scene"] = {"primary": scene, "secondary": [], "confidence": 0.7}
    if composition is not None:
        payload["composition"] = composition
    if bbox is not None:
        payload["subjects"] = [
            {
                "type": "person",
                "role": "primary",
                "confidence": 0.8,
                "bbox": bbox,
            }
        ]
    return payload


def _context(
    *,
    measurements: dict[str, object] | None = None,
    vision: dict[str, object] | None = None,
    options: AnalysisOptions | None = None,
    samples: tuple[RegionSample, ...] | None = None,
    background: float | None = 0.45,
) -> DiagnosisContext:
    values = dict(BASE_MEASUREMENTS)
    if measurements:
        values.update(measurements)
    summary = measurement_summary(**values)
    payload = vision if vision is not None else _vision()
    result = VisionResult.model_validate(payload)
    assignment = build_regions(result.subjects)
    region_samples = samples
    if region_samples is None:
        region_samples = tuple(
            RegionSample(
                region_id=region.id,
                role=SubjectRole.PRIMARY,
                type=SubjectType.PERSON,
                luminance=0.30,
            )
            for region in assignment.regions
        )
    return DiagnosisContext(
        vision=result,
        measurements=summary,
        options=options if options is not None else analysis_options(),
        assignment=assignment,
        region_samples=RegionSamples(
            samples=region_samples,
            background_luminance=background,
        ),
    )


def _types(context: DiagnosisContext) -> list[IssueType]:
    return [candidate.type for candidate in build_candidates(context).candidates]


def test_no_candidates_when_measurements_and_semantics_are_within_bounds():
    result = build_candidates(_context())
    assert result.candidates == ()
    assert result.limitations == ()


@pytest.mark.parametrize(
    ("value", "severity"),
    [(1.0, Severity.LOW), (4.9, Severity.LOW), (5.0, Severity.MEDIUM), (15.0, Severity.HIGH)],
)
def test_highlight_clipping_thresholds(value: float, severity: Severity):
    result = build_candidates(_context(measurements={"highlights_pct": value}))
    candidate = next(
        candidate
        for candidate in result.candidates
        if candidate.type is IssueType.HIGHLIGHT_CLIPPING
    )
    assert candidate.severity is severity


def test_highlight_clipping_is_absent_below_threshold():
    assert IssueType.HIGHLIGHT_CLIPPING not in _types(
        _context(measurements={"highlights_pct": 0.99})
    )


@pytest.mark.parametrize(
    ("value", "severity"),
    [(1.0, Severity.LOW), (4.9, Severity.LOW), (5.0, Severity.MEDIUM), (15.0, Severity.HIGH)],
)
def test_shadow_clipping_thresholds(value: float, severity: Severity):
    result = build_candidates(_context(measurements={"shadows_pct": value}))
    candidate = next(
        candidate for candidate in result.candidates if candidate.type is IssueType.SHADOW_CLIPPING
    )
    assert candidate.severity is severity


def test_shadow_clipping_is_absent_below_threshold():
    assert IssueType.SHADOW_CLIPPING not in _types(_context(measurements={"shadows_pct": 0.99}))


@pytest.mark.parametrize(
    ("p50", "highlights", "expected"),
    [
        (0.79, 8.0, None),
        (0.80, 4.9, None),
        (0.80, 5.0, Severity.MEDIUM),
        (0.89, 6.0, Severity.MEDIUM),
        (0.90, 6.0, Severity.HIGH),
    ],
)
def test_overexposure_requires_both_bright_median_and_clipping(
    p50: float,
    highlights: float,
    expected: Severity | None,
):
    result = build_candidates(
        _context(measurements={"luminance_p50": p50, "highlights_pct": highlights})
    )
    candidate = next(
        (candidate for candidate in result.candidates if candidate.type is IssueType.OVEREXPOSURE),
        None,
    )
    assert (candidate.severity if candidate else None) is expected


@pytest.mark.parametrize(
    ("p50", "shadows", "expected"),
    [
        (0.19, 8.0, None),
        (0.18, 4.9, None),
        (0.18, 5.0, Severity.MEDIUM),
        (0.09, 6.0, Severity.MEDIUM),
        (0.08, 6.0, Severity.HIGH),
    ],
)
def test_underexposure_requires_both_dark_median_and_clipping(
    p50: float,
    shadows: float,
    expected: Severity | None,
):
    result = build_candidates(_context(measurements={"luminance_p50": p50, "shadows_pct": shadows}))
    candidate = next(
        (candidate for candidate in result.candidates if candidate.type is IssueType.UNDEREXPOSURE),
        None,
    )
    assert (candidate.severity if candidate else None) is expected


def _subject_sample(luminance: float) -> tuple[RegionSample, ...]:
    return (
        RegionSample(
            region_id="region_001",
            role=SubjectRole.PRIMARY,
            type=SubjectType.PERSON,
            luminance=luminance,
        ),
    )


def test_backlit_subject_underexposure_detects_large_gap():
    result = build_candidates(
        _context(
            vision=_vision(direction=LightingDirection.BACK),
            samples=_subject_sample(0.20),
            background=0.45,
        )
    )
    candidate = next(
        candidate
        for candidate in result.candidates
        if candidate.type is IssueType.SUBJECT_UNDEREXPOSURE
    )
    assert candidate.severity is Severity.HIGH
    assert candidate.region_ids == ("region_001",)
    assert "0.25" in candidate.evidence


def test_backlit_subject_underexposure_requires_large_enough_gap():
    assert IssueType.SUBJECT_UNDEREXPOSURE not in _types(
        _context(
            vision=_vision(direction=LightingDirection.BACK),
            samples=_subject_sample(0.39),
            background=0.45,
        )
    )


def test_front_lit_subject_does_not_trigger_subject_underexposure():
    assert IssueType.SUBJECT_UNDEREXPOSURE not in _types(
        _context(
            vision=_vision(direction=LightingDirection.FRONT),
            samples=_subject_sample(0.20),
            background=0.45,
        )
    )


def test_bright_background_triggers_background_overexposure_when_not_backlit():
    result = build_candidates(
        _context(
            vision=_vision(direction=LightingDirection.SIDE),
            samples=_subject_sample(0.30),
            background=0.80,
        )
    )
    assert IssueType.BACKGROUND_OVEREXPOSURE in _types_from(result.candidates)


def test_dim_background_does_not_trigger_background_overexposure():
    assert IssueType.BACKGROUND_OVEREXPOSURE not in _types(
        _context(
            vision=_vision(direction=LightingDirection.SIDE),
            samples=_subject_sample(0.30),
            background=0.69,
        )
    )


@pytest.mark.parametrize(
    ("temperature", "tint", "expected"),
    [
        (7.9, 0.0, None),
        (8.0, 0.0, Severity.LOW),
        (-9.0, 9.0, Severity.LOW),
        (15.0, 0.0, Severity.MEDIUM),
    ],
)
def test_color_cast_thresholds(temperature: float, tint: float, expected: Severity | None):
    result = build_candidates(
        _context(measurements={"cast_temperature": temperature, "cast_tint": tint})
    )
    casts = [candidate for candidate in result.candidates if candidate.type is IssueType.COLOR_CAST]
    assert len(casts) <= 1
    assert (casts[0].severity if casts else None) is expected


@pytest.mark.parametrize(
    ("tilt", "expected"),
    [(1.9, None), (2.0, Severity.LOW), (5.0, Severity.MEDIUM)],
)
def test_horizon_tilt_thresholds(tilt: float, expected: Severity | None):
    result = build_candidates(_context(measurements={"horizon_tilt_deg": tilt}))
    candidate = next(
        (candidate for candidate in result.candidates if candidate.type is IssueType.HORIZON_TILT),
        None,
    )
    assert (candidate.severity if candidate else None) is expected


def test_missing_horizon_is_reported_as_a_limitation_for_landscape_scenes():
    result = build_candidates(
        _context(
            vision=_vision(scene="landscape"),
            measurements={"horizon_tilt_deg": None},
        )
    )
    assert HORIZON_UNAVAILABLE_LIMITATION in result.limitations


def test_missing_horizon_is_not_reported_for_portraits():
    result = build_candidates(_context(measurements={"horizon_tilt_deg": None}))
    assert HORIZON_UNAVAILABLE_LIMITATION not in result.limitations


@pytest.mark.parametrize(
    ("sharpness", "texture", "expected"),
    [
        (0.08, 0.1, None),
        (0.079, 0.1, Severity.LOW),
        (0.039, 0.1, Severity.MEDIUM),
    ],
)
def test_focus_issue_thresholds(
    sharpness: float,
    texture: float,
    expected: Severity | None,
):
    result = build_candidates(
        _context(
            measurements={
                "sharpness": sharpness,
                "edge_density_grid_3x3": (texture,) * 9,
            }
        )
    )
    candidate = next(
        (candidate for candidate in result.candidates if candidate.type is IssueType.FOCUS_ISSUE),
        None,
    )
    assert (candidate.severity if candidate else None) is expected


def test_high_texture_scene_suppresses_focus_issue_and_adds_limitation():
    result = build_candidates(
        _context(
            measurements={
                "sharpness": 0.03,
                "edge_density_grid_3x3": (0.2,) * 9,
            }
        )
    )
    assert IssueType.FOCUS_ISSUE not in _types_from(result.candidates)
    assert HIGH_TEXTURE_LIMITATION in result.limitations


def test_motion_blur_requires_low_sharpness_and_directional_gradients():
    result = build_candidates(
        _context(
            measurements={
                "sharpness": 0.05,
                "edge_density_grid_3x3": (0.05,) * 9,
                "gradient_anisotropy": 0.9,
            }
        )
    )

    types = _types_from(result.candidates)
    assert IssueType.MOTION_BLUR in types
    assert IssueType.FOCUS_ISSUE not in types
    assert IssueType.LOW_DETAIL not in types


def test_directional_gradients_on_a_sharp_image_do_not_trigger_motion_blur():
    result = build_candidates(
        _context(
            measurements={
                "sharpness": 0.30,
                "edge_density_grid_3x3": (0.05,) * 9,
                "gradient_anisotropy": 0.9,
            }
        )
    )

    assert IssueType.MOTION_BLUR not in _types_from(result.candidates)


def test_featureless_low_sharpness_is_reported_as_low_detail():
    result = build_candidates(
        _context(
            measurements={
                "sharpness": 0.03,
                "edge_density_grid_3x3": (0.0,) * 9,
                "gradient_anisotropy": 0.0,
            }
        )
    )

    types = _types_from(result.candidates)
    assert IssueType.LOW_DETAIL in types
    assert IssueType.FOCUS_ISSUE not in types
    assert IssueType.MOTION_BLUR not in types


def test_lighting_candidates_are_skipped_when_lighting_analysis_is_disabled():
    result = build_candidates(
        _context(
            measurements={
                "luminance_std": 0.40,
                "luminance_p1": 0.01,
                "luminance_p99": 0.99,
            },
            options=analysis_options(lighting_analysis=False),
        )
    )

    types = _types_from(result.candidates)
    assert IssueType.HARSH_CONTRAST not in types
    assert IssueType.FLAT_LIGHTING not in types


@pytest.mark.parametrize(
    ("noise", "expected"),
    [(0.34, None), (0.35, Severity.MEDIUM), (0.55, Severity.HIGH)],
)
def test_high_noise_thresholds(noise: float, expected: Severity | None):
    result = build_candidates(_context(measurements={"noise_estimate": noise}))
    candidate = next(
        (candidate for candidate in result.candidates if candidate.type is IssueType.HIGH_NOISE),
        None,
    )
    assert (candidate.severity if candidate else None) is expected


@pytest.mark.parametrize(
    ("std", "p1", "p99", "present"),
    [
        (0.29, 0.02, 0.97, False),
        (0.30, 0.05, 0.90, True),
        (0.30, 0.10, 0.90, False),
    ],
)
def test_harsh_contrast_requires_std_and_range(
    std: float,
    p1: float,
    p99: float,
    present: bool,
):
    result = build_candidates(
        _context(
            measurements={
                "luminance_std": std,
                "luminance_p1": p1,
                "luminance_p99": p99,
            }
        )
    )
    assert (IssueType.HARSH_CONTRAST in _types_from(result.candidates)) is present


def test_flat_lighting_is_detected_for_narrow_range():
    result = build_candidates(
        _context(
            measurements={
                "luminance_std": 0.05,
                "luminance_p1": 0.44,
                "luminance_p99": 0.54,
            }
        )
    )
    assert IssueType.FLAT_LIGHTING in _types_from(result.candidates)


def test_unbalanced_composition_creates_candidate():
    result = build_candidates(
        _context(
            vision=_vision(
                composition={
                    "balance": "unbalanced",
                    "subjectPosition": "left",
                    "negativeSpace": "moderate",
                    "confidence": 0.6,
                }
            )
        )
    )
    assert IssueType.BALANCE_ISSUE in _types_from(result.candidates)


def test_low_negative_space_with_large_subject_creates_candidate():
    result = build_candidates(
        _context(
            vision=_vision(
                composition={
                    "balance": "moderate",
                    "subjectPosition": "center",
                    "negativeSpace": "low",
                    "confidence": 0.6,
                },
                bbox={"x": 0.1, "y": 0.1, "width": 0.6, "height": 0.7},
            )
        )
    )
    assert IssueType.NEGATIVE_SPACE_ISSUE in _types_from(result.candidates)


def test_subject_touching_frame_edge_creates_placement_candidate():
    result = build_candidates(
        _context(
            vision=_vision(
                composition={
                    "balance": "moderate",
                    "subjectPosition": "left",
                    "negativeSpace": "moderate",
                    "confidence": 0.6,
                },
                bbox={"x": 0.0, "y": 0.2, "width": 0.4, "height": 0.6},
            )
        )
    )
    assert IssueType.SUBJECT_PLACEMENT in _types_from(result.candidates)


def test_candidate_order_is_stable_and_sorted():
    context = _context(
        measurements={
            "luminance_p50": 0.92,
            "highlights_pct": 20.0,
            "cast_temperature": 20.0,
            "sharpness": 0.02,
            "noise_estimate": 0.6,
            "luminance_std": 0.35,
            "luminance_p1": 0.0,
            "luminance_p99": 1.0,
        }
    )
    first = build_candidates(context).candidates
    second = build_candidates(context).candidates
    assert first == second

    rank = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
    keys = [
        (rank[candidate.severity], -candidate.confidence, candidate.type.value, candidate.id)
        for candidate in first
    ]
    assert keys == sorted(keys)


def test_quality_diagnosis_option_disables_all_candidates():
    result = build_candidates(
        _context(
            measurements={"highlights_pct": 20.0},
            options=analysis_options(quality_diagnosis=False),
        )
    )
    assert result.candidates == ()
    assert result.limitations == ()


def test_color_option_disables_color_cast():
    result = build_candidates(
        _context(
            measurements={"cast_temperature": 20.0},
            options=analysis_options(color_analysis=False),
        )
    )
    assert IssueType.COLOR_CAST not in _types_from(result.candidates)


def test_composition_option_disables_composition_candidates_and_limitations():
    result = build_candidates(
        _context(
            vision=_vision(
                scene="landscape",
                composition={
                    "balance": "unbalanced",
                    "subjectPosition": "left",
                    "negativeSpace": "low",
                    "confidence": 0.6,
                },
            ),
            options=analysis_options(composition_analysis=False),
        )
    )
    assert IssueType.BALANCE_ISSUE not in _types_from(result.candidates)
    assert HORIZON_UNAVAILABLE_LIMITATION not in result.limitations


def test_subject_option_disables_subject_related_candidates():
    result = build_candidates(
        _context(
            vision=_vision(direction=LightingDirection.BACK),
            samples=_subject_sample(0.2),
            background=0.9,
            options=analysis_options(subject_detection=False),
        )
    )
    assert IssueType.SUBJECT_UNDEREXPOSURE not in _types_from(result.candidates)
    assert IssueType.BACKGROUND_OVEREXPOSURE not in _types_from(result.candidates)


def test_sample_regions_measures_primary_and_background_luminance():
    rgb = np.zeros((100, 200, 3), dtype=np.float32)
    rgb[:, :100] = 0.05
    rgb[:, 100:] = 0.95
    image = LoadedImage(rgb=rgb)
    result = VisionResult.model_validate(
        vision_payload(
            subjects=[
                {
                    "type": "person",
                    "role": "primary",
                    "confidence": 0.8,
                    "bbox": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0},
                },
                {
                    "type": "plant",
                    "role": "secondary",
                    "confidence": 0.6,
                    "bbox": {"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0},
                },
            ]
        )
    )
    assignment = build_regions(result.subjects)

    samples = sample_regions(image, assignment)

    by_id = {sample.region_id: sample for sample in samples.samples}
    assert by_id["region_001"].role is SubjectRole.PRIMARY
    assert by_id["region_001"].luminance == pytest.approx(0.05, abs=0.01)
    assert by_id["region_002"].luminance > 0.8
    assert samples.background_luminance is not None
    assert samples.background_luminance > 0.8


def _types_from(candidates) -> list[IssueType]:
    return [candidate.type for candidate in candidates]
