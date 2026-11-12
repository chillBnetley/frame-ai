"""V6.2 quality-assurance checks over the legal eight-scene synthetic set.

The images are original deterministic patterns documented in
``docs/evaluation/stage6-test-set.md``. They verify pipeline stability and scene
separation; real photographic judgement still requires the licensed human test set.
"""

from __future__ import annotations

import numpy as np

from app.models.visual_dna import FeatureOrigin
from app.visual_dna.extractor import extract_photo_features
from tests.test_stage6_matrix import SCENES, scene_image

EXPECTED_SCENES = {
    "street",
    "portrait",
    "architecture",
    "landscape",
    "night",
    "indoor",
    "backlit",
    "lowlight",
}


def test_eight_scene_dataset_is_legal_reproducible_and_reasoned() -> None:
    assert set(SCENES) == EXPECTED_SCENES
    for name, analysis in SCENES.items():
        first = scene_image(name)
        again = scene_image(name)
        assert first.shape == (96, 128, 3), name
        assert np.array_equal(first, again), name
        assert float(first.min()) >= 0.0 and float(first.max()) <= 1.0, name

        features = extract_photo_features(analysis)
        assert features.scene.primary is analysis.scene.primary, name
        assert features.image_id == analysis.image.id, name
        assert features.readings, name
        assert all(reading.evidence for reading in features.readings), name
        assert any(reading.origin is FeatureOrigin.MEASUREMENT for reading in features.readings), (
            name
        )
        assert any(reading.origin is FeatureOrigin.MODEL for reading in features.readings), name


def test_eight_scene_dataset_separates_tone_and_low_light_cases() -> None:
    night = extract_photo_features(SCENES["night"])
    lowlight = extract_photo_features(SCENES["lowlight"])
    assert night.tone.low_light is True
    assert lowlight.tone.low_light is True

    landscape = extract_photo_features(SCENES["landscape"])
    indoor = extract_photo_features(SCENES["indoor"])
    assert landscape.tone.contrast_strength > indoor.tone.contrast_strength
    assert lowlight.tone.contrast_strength < landscape.tone.contrast_strength

    portrait = extract_photo_features(SCENES["portrait"])
    assert portrait.tone.low_light is False
