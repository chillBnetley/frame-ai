from __future__ import annotations

import pytest

from app.ai.base import DecisionRequest, ModelImage, VisionRequest
from app.ai.contracts import (
    ExposureQuality,
    LightingDirection,
    NoiseLevel,
    Severity,
    SharpnessQuality,
    VisionResult,
)
from app.ai.providers.mock import (
    MOCK_DECISION_LIMITATION,
    MOCK_LIMITATION,
    MockDecisionProvider,
    MockVisionProvider,
)
from tests.ai_support import (
    analysis_options,
    issue_candidate,
    measurement_summary,
    vision_payload,
)


def vision_request() -> VisionRequest:
    return VisionRequest(
        image=ModelImage(data=b"fake", mime_type="image/jpeg", width=64, height=64),
        options=analysis_options(),
        measurements=measurement_summary(),
    )


def decision_request(candidates=None) -> DecisionRequest:
    return DecisionRequest(
        vision=VisionResult.model_validate(vision_payload()),
        measurements=measurement_summary(),
        candidates=tuple(candidates or ()),
        options=analysis_options(),
    )


def test_mock_vision_is_deterministic_and_marked():
    provider = MockVisionProvider("portrait")

    first = provider.analyze(vision_request())
    second = provider.analyze(vision_request())

    assert first == second
    assert provider.is_mock is True
    assert provider.name == "mock"
    assert MOCK_LIMITATION in first.limitations


@pytest.mark.parametrize("scenario", ["generic", "portrait", "landscape", "low_light", "backlit"])
def test_mock_scenarios_are_valid_and_confidence_is_bounded(scenario):
    result = MockVisionProvider(scenario).analyze(vision_request())

    assert result.scene.confidence <= 0.5
    assert result.lighting.confidence <= 0.5
    assert result.color.confidence <= 0.5
    assert result.composition.confidence <= 0.5
    assert all(subject.confidence <= 0.5 for subject in result.subjects)
    assert MOCK_LIMITATION in result.limitations


def test_unknown_mock_scenario_falls_back_to_generic():
    result = MockVisionProvider("does-not-exist").analyze(vision_request())

    assert result.scene.primary == "other"
    assert result.subjects == ()
    assert result.lighting.direction == LightingDirection.UNKNOWN


def test_mock_decision_selects_only_supplied_candidates():
    candidates = (
        issue_candidate(id="low", severity=Severity.LOW, confidence=0.9, evidence="低风险。"),
        issue_candidate(id="high", severity=Severity.HIGH, confidence=0.5, evidence="高风险。"),
        issue_candidate(id="medium", severity=Severity.MEDIUM, confidence=0.8, evidence="中风险。"),
        issue_candidate(id="extra", severity=Severity.LOW, confidence=0.1, evidence="额外。"),
    )

    result = MockDecisionProvider().diagnose(decision_request(candidates))

    selected = [issue.candidate_id for issue in result.issues]
    assert selected == ["high", "medium", "low"]
    assert len(result.recommendations) == len(result.issues)
    assert set(selected) <= {candidate.id for candidate in candidates}
    assert MOCK_DECISION_LIMITATION in result.limitations


def test_mock_decision_without_candidates_produces_no_issues():
    result = MockDecisionProvider().diagnose(decision_request())

    assert result.issues == ()
    assert result.recommendations == ()
    assert result.technical_quality.confidence <= 0.5
    assert MOCK_DECISION_LIMITATION in result.limitations


@pytest.mark.parametrize(
    ("measurements", "exposure", "sharpness", "noise"),
    [
        (
            measurement_summary(luminance_p50=0.1, sharpness=0.02, noise_estimate=0.8),
            ExposureQuality.SLIGHTLY_UNDEREXPOSED,
            SharpnessQuality.POOR,
            NoiseLevel.HIGH,
        ),
        (
            measurement_summary(luminance_p50=0.5, sharpness=0.1, noise_estimate=0.3),
            ExposureQuality.BALANCED,
            SharpnessQuality.SOFT,
            NoiseLevel.MODERATE,
        ),
        (
            measurement_summary(luminance_p50=0.9, sharpness=0.6, noise_estimate=0.05),
            ExposureQuality.SLIGHTLY_OVEREXPOSED,
            SharpnessQuality.GOOD,
            NoiseLevel.LOW,
        ),
    ],
)
def test_mock_decision_technical_quality_thresholds(measurements, exposure, sharpness, noise):
    request = DecisionRequest(
        vision=VisionResult.model_validate(vision_payload()),
        measurements=measurements,
        candidates=(),
        options=analysis_options(),
    )

    result = MockDecisionProvider().diagnose(request)

    assert result.technical_quality.exposure == exposure
    assert result.technical_quality.sharpness == sharpness
    assert result.technical_quality.noise == noise
