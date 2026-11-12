from __future__ import annotations

from app.ai.contracts import SceneLabel
from app.models.analysis_report import EngineInfo
from app.models.visual_dna import FeatureOrigin, PhotoVisualFeatures
from app.visual_dna.extractor import EXTRACTOR_VERSION, extract_photo_features
from tests.photographer_support import report


def _reading(features: PhotoVisualFeatures, key: str):
    return next(reading for reading in features.readings if reading.key == key)


def test_objective_and_subjective_readings_stay_distinct() -> None:
    features = extract_photo_features(
        report(
            scene=SceneLabel.STREET,
            cast_temperature=18.0,
            cast_tint=-9.0,
            saturation_mean=0.18,
            luminance_std=0.10,
            highlights_pct=2.0,
            shadows_pct=1.0,
            sharpness=0.45,
            noise_estimate=0.10,
        )
    )

    assert features.extractor_version == EXTRACTOR_VERSION
    assert features.color.temperature_offset == 0.18
    assert features.color.tint_offset == -0.09
    assert features.color.monochrome is False
    assert round(features.tone.contrast_strength, 3) == 0.286
    assert features.light.directional is True
    assert features.light.softness < 0.5

    objective = _reading(features, "castTemperature")
    assert objective.origin is FeatureOrigin.MEASUREMENT
    assert objective.editable is False
    assert objective.evidence == ("measurement.color.cast.temperature",)

    interpretation = _reading(features, "saturationIntent")
    assert interpretation.origin is FeatureOrigin.DERIVED
    assert interpretation.editable is True
    assert interpretation.value == "restrained"

    model_reading = _reading(features, "primary")
    assert model_reading.origin is FeatureOrigin.MODEL
    assert model_reading.editable is True
    assert model_reading.value == "street"


def test_monochrome_and_low_high_key_are_detected() -> None:
    base = report(saturation_mean=0.01, luminance_p50=0.1)
    low_key_luminance = base.measurements.luminance.model_copy(update={"p95": 0.5})
    low_key_report = base.model_copy(
        update={
            "measurements": base.measurements.model_copy(update={"luminance": low_key_luminance})
        }
    )
    monochrome = extract_photo_features(low_key_report)
    assert monochrome.color.monochrome is True
    assert monochrome.tone.low_light is True
    assert monochrome.tone.low_key is True
    assert _reading(monochrome, "saturationIntent").value == "restrained"

    high_key = extract_photo_features(report(luminance_p50=0.82))
    assert high_key.tone.high_key is True
    assert high_key.tone.low_key is False


def test_anomalies_flag_clipping_focus_noise_and_unknown_scene() -> None:
    features = extract_photo_features(
        report(
            scene=SceneLabel.OTHER,
            highlights_pct=12.0,
            shadows_pct=14.0,
            sharpness=0.05,
            noise_estimate=0.40,
        )
    )
    codes = {anomaly.code for anomaly in features.anomalies}
    assert {
        "scene_unknown",
        "highlights_clipped",
        "shadows_clipped",
        "low_sharpness",
        "high_noise",
    } <= codes


def test_low_confidence_reduces_overall_confidence_and_records_limits() -> None:
    base = report()
    weak = base.model_copy(
        update={
            "scene": base.scene.model_copy(update={"confidence": 0.2}),
            "lighting": base.lighting.model_copy(update={"confidence": 0.2}),
            "color": base.color.model_copy(update={"confidence": 0.2}),
            "composition": base.composition.model_copy(update={"confidence": 0.2}),
            "technical_quality": base.technical_quality.model_copy(update={"confidence": 0.2}),
        }
    )
    features = extract_photo_features(weak)
    codes = {anomaly.code for anomaly in features.anomalies}
    assert {"low_scene_confidence", "low_light_confidence", "low_color_confidence"} <= codes
    assert features.overall_confidence < 0.5
    assert any("模拟" in limitation for limitation in features.limitations)
    assert any("置信度较低" in limitation for limitation in features.limitations)


def test_real_provider_reports_do_not_carry_the_mock_limitation() -> None:
    mock_report = report()
    real_report = mock_report.model_copy(
        update={
            "engine": EngineInfo(
                vision_provider="openai",
                vision_model="qwen",
                decision_provider="openai",
                decision_model="deepseek",
                prompt_version="stage3/2",
                analyzer_version="frame-analyzer/1",
                is_mock=False,
            )
        }
    )
    mock_features = extract_photo_features(mock_report)
    real_features = extract_photo_features(real_report)

    assert mock_features.is_mock is True
    assert real_features.is_mock is False
    assert any("模拟" in limitation for limitation in mock_features.limitations)
    assert all("模拟" not in limitation for limitation in real_features.limitations)
    assert real_features.overall_confidence > mock_features.overall_confidence


def test_high_noise_is_not_a_grain_preference() -> None:
    features = extract_photo_features(report(sharpness=0.5, noise_estimate=0.55))

    assert _reading(features, "intent").value == "noisy"
    assert "画质限制" in _reading(features, "intent").description
    assert features.texture.grain_tendency == 0.55


def test_low_sharpness_is_not_a_soft_focus_preference() -> None:
    features = extract_photo_features(report(sharpness=0.04, noise_estimate=0.05))

    assert _reading(features, "intent").value == "quality_soft"
    assert "柔焦" in _reading(features, "intent").description


def test_every_reading_has_evidence_and_a_unique_key() -> None:
    features = extract_photo_features(report())
    keys = [(reading.category, reading.key) for reading in features.readings]
    assert len(keys) == len(set(keys))
    assert all(reading.evidence for reading in features.readings)
    assert {reading.category.value for reading in features.readings} == {
        "color",
        "tone",
        "light",
        "texture",
        "scene",
        "composition",
    }
