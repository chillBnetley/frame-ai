from __future__ import annotations

import app.ai  # noqa: F401  # initialise the ai package before model imports
from app.ai.contracts import SceneLabel
from app.models.style_fit import ConversionMode, FitDimension, FitLevel
from app.photographer.validator import known_evidence_refs
from app.styles.fit import evaluate_style_fit
from app.styles.library import (
    ANSEL_ADAMS,
    BW_DOCUMENTARY,
    FAN_HO,
    SAUL_LEITER,
    STEVE_MCCURRY,
)
from tests.photographer_support import report

PROFILES = (ANSEL_ADAMS, BW_DOCUMENTARY, FAN_HO, SAUL_LEITER, STEVE_MCCURRY)


def _dimension(evaluation, dimension: FitDimension):
    return next(item for item in evaluation.dimensions if item.dimension is dimension)


def test_street_profile_fits_a_low_saturation_street_report():
    analysis = report(scene=SceneLabel.STREET, saturation_mean=0.25)

    evaluation = evaluate_style_fit(SAUL_LEITER, analysis)

    assert evaluation.overall_level is FitLevel.HIGH
    assert evaluation.overall_score >= 70.0
    assert evaluation.recommended_mode is ConversionMode.STYLE
    assert evaluation.recommended_strength.minimum == 0.5
    assert evaluation.recommended_strength.maximum == 0.75
    assert evaluation.conflicts == ()


def test_scene_mismatch_caps_the_overall_score_and_stays_honest():
    evaluation = evaluate_style_fit(FAN_HO, report(scene=SceneLabel.PORTRAIT))

    scene = _dimension(evaluation, FitDimension.SCENE)
    assert scene.level is FitLevel.UNSUITABLE
    assert scene.score < 30.0
    assert evaluation.overall_score <= 38.0
    assert evaluation.overall_level in {FitLevel.LOW, FitLevel.UNSUITABLE}
    assert evaluation.recommended_mode is ConversionMode.CREATIVE
    assert evaluation.recommended_strength.maximum <= 0.4

    scene_conflict = next(
        item for item in evaluation.conflicts if item.dimension is FitDimension.SCENE
    )
    assert scene_conflict.improvable is False
    assert any("场景" in text for text in evaluation.unachievable)


def test_unknown_scene_never_reaches_a_high_overall_score():
    analysis = report(scene=SceneLabel.OTHER)

    for profile in PROFILES:
        evaluation = evaluate_style_fit(profile, analysis)
        assert evaluation.overall_score <= 60.0
        assert evaluation.overall_level is not FitLevel.HIGH


def test_low_analysis_confidence_caps_the_overall_score():
    analysis = report()
    analysis = analysis.model_copy(
        update={
            "scene": analysis.scene.model_copy(update={"confidence": 0.2}),
            "lighting": analysis.lighting.model_copy(update={"confidence": 0.2}),
            "color": analysis.color.model_copy(update={"confidence": 0.2}),
            "composition": analysis.composition.model_copy(update={"confidence": 0.2}),
            "technical_quality": analysis.technical_quality.model_copy(update={"confidence": 0.2}),
        }
    )

    evaluation = evaluate_style_fit(STEVE_MCCURRY, analysis)

    assert evaluation.overall_score <= 49.0
    assert evaluation.overall_level is FitLevel.LOW
    assert any("人工复核" in text for text in evaluation.limitations)
    assert any("场景" in text for text in evaluation.limitations)


def test_monochrome_style_does_not_treat_colour_as_a_blocker():
    analysis = report(scene=SceneLabel.LANDSCAPE, saturation_mean=0.62)

    evaluation = evaluate_style_fit(ANSEL_ADAMS, analysis)

    color = _dimension(evaluation, FitDimension.COLOR)
    assert color.score >= 70.0
    assert not any(item.dimension is FitDimension.COLOR for item in evaluation.conflicts)


def test_missing_person_blocks_a_portrait_style():
    analysis = report(scene=SceneLabel.PORTRAIT).model_copy(update={"subjects": ()})

    evaluation = evaluate_style_fit(STEVE_MCCURRY, analysis)

    subject = _dimension(evaluation, FitDimension.SUBJECT)
    assert subject.level is FitLevel.UNSUITABLE
    assert evaluation.overall_score <= 45.0
    conflict = next(item for item in evaluation.conflicts if item.dimension is FitDimension.SUBJECT)
    assert conflict.improvable is False
    assert any("人物" in text for text in evaluation.unachievable)


def test_conflicts_separate_post_fixes_from_capture_conditions():
    analysis = report(scene=SceneLabel.PORTRAIT, highlights_pct=12.0)

    evaluation = evaluate_style_fit(FAN_HO, analysis)

    scene_conflict = next(
        item for item in evaluation.conflicts if item.dimension is FitDimension.SCENE
    )
    light_conflict = next(
        item for item in evaluation.conflicts if item.dimension is FitDimension.LIGHT
    )
    assert scene_conflict.improvable is False
    assert light_conflict.improvable is True
    assert any("高光" in text for text in evaluation.unachievable)


def test_recommended_strength_order_and_mode_track_the_fit_level():
    cases = {
        "high": evaluate_style_fit(SAUL_LEITER, report(scene=SceneLabel.STREET)),
        "medium": evaluate_style_fit(SAUL_LEITER, report(scene=SceneLabel.OTHER)),
        "low": evaluate_style_fit(FAN_HO, report(scene=SceneLabel.PORTRAIT)),
    }

    assert cases["high"].overall_level is FitLevel.HIGH
    assert cases["high"].recommended_mode is ConversionMode.STYLE
    assert cases["medium"].overall_level is FitLevel.MEDIUM
    assert cases["medium"].recommended_mode is ConversionMode.NATURAL
    assert cases["low"].recommended_mode is ConversionMode.CREATIVE

    for evaluation in cases.values():
        strength = evaluation.recommended_strength
        assert strength.minimum <= strength.default <= strength.maximum


def test_evaluation_is_deterministic():
    analysis = report(scene=SceneLabel.STREET)

    first = evaluate_style_fit(SAUL_LEITER, analysis)
    second = evaluate_style_fit(SAUL_LEITER, analysis)

    assert first == second


def test_every_dimension_cites_real_report_evidence():
    analysis = report(scene=SceneLabel.PORTRAIT, highlights_pct=8.0)
    known = known_evidence_refs(analysis)

    for profile in PROFILES:
        evaluation = evaluate_style_fit(profile, analysis)
        assert {item.dimension for item in evaluation.dimensions} == set(FitDimension)
        assert len(evaluation.dimensions) == 5
        for dimension in evaluation.dimensions:
            assert 0.0 <= dimension.score <= 100.0
            assert dimension.basis
            assert dimension.evidence_refs
            assert set(dimension.evidence_refs) <= known
        for conflict in evaluation.conflicts:
            assert set(conflict.evidence_refs) <= known
