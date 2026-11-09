from __future__ import annotations

from typing import Any

from app.ai.contracts import ContrastLevel, LightingDirection, SceneLabel
from app.models.analysis_report import EngineInfo
from app.models.personal_style import PersonalAvoidEffect
from app.models.visual_dna import PhotoVisualFeatures
from app.visual_dna.extractor import extract_photo_features
from app.visual_dna.fusion import FusionPhoto, fuse_photo_features, fusion_weight
from tests.photographer_support import report


def _features(
    *,
    scene: SceneLabel = SceneLabel.STREET,
    saturation: float = 0.20,
    temperature: float = -0.10,
    contrast_std: float = 0.08,
    contrast: ContrastLevel = ContrastLevel.LOW,
    direction: LightingDirection = LightingDirection.DIFFUSE,
    sharpness: float = 0.40,
    noise: float = 0.12,
    highlights_pct: float = 1.0,
    shadows_pct: float = 1.0,
    is_mock: bool = False,
) -> PhotoVisualFeatures:
    base = report(
        scene=scene,
        saturation_mean=saturation,
        cast_temperature=temperature * 100.0,
        luminance_std=contrast_std,
        contrast=contrast,
        sharpness=sharpness,
        noise_estimate=noise,
        highlights_pct=highlights_pct,
        shadows_pct=shadows_pct,
    )
    engine = EngineInfo(
        vision_provider="mock" if is_mock else "openai",
        vision_model="mock-vision" if is_mock else "qwen",
        decision_provider="mock" if is_mock else "openai",
        decision_model="mock-decision" if is_mock else "deepseek",
        prompt_version="stage3/2",
        analyzer_version="frame-analyzer/1",
        is_mock=is_mock,
    )
    return extract_photo_features(
        base.model_copy(
            update={
                "engine": engine,
                "scene": base.scene.model_copy(update={"confidence": 0.9}),
                "lighting": base.lighting.model_copy(
                    update={
                        "direction": direction,
                        "contrast": contrast,
                        "confidence": 0.9,
                    }
                ),
                "color": base.color.model_copy(update={"confidence": 0.9}),
                "composition": base.composition.model_copy(update={"confidence": 0.9}),
                "technical_quality": base.technical_quality.model_copy(
                    update={"confidence": 0.9}
                ),
            }
        )
    )


def _photos(count: int, **kwargs: Any) -> list[FusionPhoto]:
    return [
        FusionPhoto(reference_id=f"ref-{index}", image_id=None, features=_features(**kwargs))
        for index in range(count)
    ]


def test_consistent_photos_produce_a_stable_profile() -> None:
    outcome = fuse_photo_features(_photos(5))

    assert outcome.sample_count == 5
    assert outcome.confidence > 0.5
    assert outcome.stability["color"] >= 0.9
    assert outcome.stability["tone"] >= 0.9
    assert outcome.stability["light"] >= 0.9
    assert outcome.stability["texture"] >= 0.9
    assert outcome.targets["saturation"] < 0
    assert outcome.targets["temperature"] < 0
    assert outcome.conflicts == ()
    assert outcome.scenes[0].scene is SceneLabel.STREET
    assert outcome.scenes[0].photo_count == 5
    assert outcome.scene_fit.suitable == (SceneLabel.STREET,)
    assert outcome.default_strength >= 0.35


def test_conflicting_preferences_are_reported_not_averaged() -> None:
    photos = _photos(
        3,
        saturation=0.60,
        temperature=0.12,
        contrast_std=0.30,
        contrast=ContrastLevel.HIGH,
        direction=LightingDirection.SIDE,
    ) + [
        FusionPhoto(
            reference_id=f"cool-{index}",
            image_id=None,
            features=_features(
                saturation=0.18,
                temperature=-0.12,
                contrast_std=0.04,
                contrast=ContrastLevel.LOW,
                direction=LightingDirection.DIFFUSE,
            ),
        )
        for index in range(3)
    ]
    outcome = fuse_photo_features(photos)

    dimensions = {conflict.dimension for conflict in outcome.conflicts}
    assert {"color.saturation", "color.temperature", "tone.contrast"} <= dimensions
    assert "saturation" not in outcome.targets
    assert "temperature" not in outcome.targets
    assert "contrast" not in outcome.targets
    assert any("冲突" in limitation for limitation in outcome.limitations)
    assert outcome.confidence < fuse_photo_features(_photos(6)).confidence

    minority = fuse_photo_features(
        _photos(5, saturation=0.18)
        + [
            FusionPhoto(
                reference_id="vivid-minority",
                image_id=None,
                features=_features(saturation=0.62),
            )
        ]
    )
    assert any("个别特征" in message for message in minority.occasional)
    assert minority.targets["saturation"] < 0


def test_scene_differences_are_kept_as_scene_targets() -> None:
    photos = (
        _photos(2, scene=SceneLabel.STREET)
        + _photos(2, scene=SceneLabel.PORTRAIT)
        + _photos(2, scene=SceneLabel.ARCHITECTURE)
    )
    outcome = fuse_photo_features(photos)

    assert set(outcome.scene_targets) == {
        SceneLabel.STREET,
        SceneLabel.PORTRAIT,
        SceneLabel.ARCHITECTURE,
    }
    assert all(item.photo_count == 2 for item in outcome.scenes)
    assert outcome.stability["color"] >= 0.9
    assert outcome.stability["scene"] < 0.5
    assert set(outcome.scene_fit.suitable) == {
        SceneLabel.STREET,
        SceneLabel.PORTRAIT,
        SceneLabel.ARCHITECTURE,
    }
    assert any("场景差异" in limitation for limitation in outcome.limitations)


def test_too_few_photos_lower_confidence_and_are_flagged() -> None:
    outcome = fuse_photo_features(_photos(1))

    assert outcome.sample_count == 1
    assert outcome.confidence < 0.3
    assert any("少于 3 张" in limitation for limitation in outcome.limitations)
    assert 0.35 <= outcome.default_strength < 0.45


def test_adding_opposing_photos_changes_the_fused_direction() -> None:
    low_saturation = _photos(3)
    before = fuse_photo_features(low_saturation)
    high_saturation = [
        FusionPhoto(
            reference_id=f"vivid-{index}",
            image_id=None,
            features=_features(saturation=0.62, temperature=0.12),
        )
        for index in range(3)
    ]
    after = fuse_photo_features([*low_saturation, *high_saturation])

    assert before.targets["saturation"] < 0
    assert "saturation" not in after.targets
    assert any(conflict.dimension == "color.saturation" for conflict in after.conflicts)
    assert after.sample_count == 6


def test_monochrome_references_keep_a_monochrome_target_and_envelope() -> None:
    outcome = fuse_photo_features(_photos(5, saturation=0.01))

    assert outcome.targets["saturation"] == -100.0
    assert outcome.envelope.saturation == 100.0
    assert "黑白" in outcome.color.tendency
    assert "去饱和" in outcome.color.saturation


def test_user_avoid_rules_become_protection_constraints() -> None:
    outcome = fuse_photo_features(
        _photos(5),
        avoid=(
            PersonalAvoidEffect.UNNATURAL_SKIN,
            PersonalAvoidEffect.OVERSATURATED,
        ),
    )
    values = {item.value for item in outcome.constraints}
    assert "preserve_skin_tone" in values
    assert "avoid_extreme_saturation" in values
    assert outcome.summary
    assert len(outcome.sections) == 6


def test_anomalous_photos_contribute_less_and_are_counted() -> None:
    clean = _features()
    clipped = _features(highlights_pct=15.0, shadows_pct=15.0)
    outcome = fuse_photo_features(
        [
            FusionPhoto(reference_id="clean", image_id=None, features=clean),
            *[
                FusionPhoto(reference_id=f"clipped-{index}", image_id=None, features=clipped)
                for index in range(3)
            ],
        ]
    )

    assert fusion_weight(clipped) < fusion_weight(clean)
    assert outcome.anomaly_count == 3
    assert any("异常" in limitation for limitation in outcome.limitations)


def test_mock_analysis_lowers_confidence_versus_real_analysis() -> None:
    real = fuse_photo_features(_photos(5, is_mock=False))
    mock = fuse_photo_features(_photos(5, is_mock=True))

    assert mock.confidence < real.confidence
    assert any("模拟" in limitation for limitation in mock.limitations)
    assert all("模拟" not in limitation for limitation in real.limitations)
