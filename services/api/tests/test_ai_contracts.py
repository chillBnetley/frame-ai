from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.contracts import (
    AnalysisOptions,
    BBox,
    ColorResult,
    DecisionResult,
    IssueCandidate,
    MeasurementSummary,
    SceneResult,
    VisionResult,
)
from tests.ai_support import (
    decision_payload,
    issue_candidate,
    measurement_summary,
    vision_payload,
)


def test_analysis_options_requires_at_least_one_enabled_option():
    with pytest.raises(ValidationError, match="At least one analysis option"):
        AnalysisOptions(
            scene_recognition=False,
            subject_detection=False,
            lighting_analysis=False,
            color_analysis=False,
            composition_analysis=False,
            quality_diagnosis=False,
        )


def test_analysis_options_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        AnalysisOptions(unknown_option=True)


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": -0.1, "y": 0.0, "width": 0.2, "height": 0.2},
        {"x": 0.9, "y": 0.0, "width": 0.2, "height": 0.2},
        {"x": 0.0, "y": 0.9, "width": 0.2, "height": 0.2},
        {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.2},
        {"x": 0.0, "y": 0.0, "width": 0.2, "height": 1.2},
    ],
)
def test_bbox_rejects_out_of_bounds_values(bbox):
    with pytest.raises(ValidationError):
        BBox(**bbox)


def test_bbox_accepts_full_frame_with_tolerance():
    box = BBox(x=0.0, y=0.0, width=1.0, height=1.0)
    assert box.width == 1.0


def test_scene_rejects_duplicate_secondary_and_primary_overlap():
    with pytest.raises(ValidationError, match="must be unique"):
        SceneResult(primary="portrait", secondary=("street", "street"), confidence=0.5)

    with pytest.raises(ValidationError, match="must not appear in secondary"):
        SceneResult(primary="portrait", secondary=("portrait",), confidence=0.5)


def test_color_normalizes_hex_and_enforces_five_colors():
    result = ColorResult(
        temperature="warm",
        saturation="low",
        dominant_colors=("#aabbcc",),
        confidence=0.5,
    )
    assert result.dominant_colors == ("#AABBCC",)

    with pytest.raises(ValidationError, match="at most 5 items"):
        ColorResult(
            temperature="warm",
            saturation="low",
            dominant_colors=("#000000",) * 6,
            confidence=0.5,
        )

    with pytest.raises(ValidationError):
        ColorResult(
            temperature="warm",
            saturation="low",
            dominant_colors=("#GGGGGG",),
            confidence=0.5,
        )


def test_measurement_summary_enforces_ranges():
    with pytest.raises(ValidationError):
        measurement_summary(luminance_p50=1.4)
    with pytest.raises(ValidationError):
        measurement_summary(width=0)
    with pytest.raises(ValidationError):
        measurement_summary(noise_estimate=-0.1)


def test_measurement_summary_requires_a_normalized_histogram():
    with pytest.raises(ValidationError, match="histogram32 must sum to 1"):
        measurement_summary(histogram32=(0.0,) * 32)

    with pytest.raises(ValidationError):
        measurement_summary(histogram32=(1.0,) * 31)

    with pytest.raises(ValidationError):
        measurement_summary(edge_density_grid_3x3=(0.1,) * 8)


def test_contracts_accept_camel_and_snake_case_aliases():
    camel = VisionResult.model_validate(vision_payload())
    assert camel.scene.primary == "portrait"
    assert camel.color.dominant_colors == ("#C58B6A",)
    assert camel.composition.subject_position == "center"

    snake = camel.model_dump()
    assert VisionResult.model_validate(snake) == camel

    aliased = camel.model_dump(mode="json", by_alias=True)
    assert aliased["color"]["dominantColors"] == ["#C58B6A"]
    assert aliased["composition"]["subjectPosition"] == "center"


def test_contracts_reject_extra_keys():
    payload = vision_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        VisionResult.model_validate(payload)


def test_issue_candidate_evidence_ref_source_is_constrained():
    with pytest.raises(ValidationError):
        issue_candidate(
            evidence_refs=({"source": "guess", "key": "luminanceP50", "value": "0.12"},)
        )


def test_decision_result_accepts_camel_aliases():
    result = DecisionResult.model_validate(decision_payload())
    assert result.technical_quality.exposure == "slightly_underexposed"
    assert result.issues[0].candidate_id == "c1"
    assert result.recommendations[0].target_regions == ("r1",)


def test_frozen_contracts_cannot_be_mutated():
    measurement = measurement_summary()
    with pytest.raises(ValidationError):
        measurement.width = 10


def test_issue_candidate_identifier_is_bounded():
    with pytest.raises(ValidationError):
        IssueCandidate(
            id="",
            type="underexposure",
            severity="high",
            confidence=0.5,
            evidence="证据",
        )


def test_measurement_summary_round_trips_with_aliases():
    measurement: MeasurementSummary = measurement_summary()
    assert MeasurementSummary.model_validate(measurement.model_dump(by_alias=True)) == measurement
