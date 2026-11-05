from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eval_analysis.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_analysis", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eval_analysis = _load_script()


def _manifest(tmp_path: Path, expected: dict[str, object], image: str = "img.png") -> Path:
    (tmp_path / image).write_bytes(b"not-a-real-image")
    payload = {
        "dataset": "unit",
        "cases": [{"id": "case-1", "image": image, "expected": expected}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_accepts_supported_labels(tmp_path: Path):
    path = _manifest(
        tmp_path,
        {
            "scene": {"primary": "portrait", "secondary": ["indoor"]},
            "subjects": ["person"],
            "lighting": {"direction": "side", "type": "natural"},
            "issues": ["underexposure"],
        },
    )
    manifest = eval_analysis.load_manifest(path)
    case = manifest["cases"][0]
    assert manifest["dataset"] == "unit"
    assert case["image"] == "img.png"
    assert case["expected"]["scene"]["primary"] == "portrait"


def test_load_manifest_rejects_unknown_expected_key(tmp_path: Path):
    path = _manifest(tmp_path, {"scenes": ["portrait"]})
    with pytest.raises(eval_analysis.ManifestError, match="unsupported expected keys"):
        eval_analysis.load_manifest(path)


def test_load_manifest_rejects_missing_image(tmp_path: Path):
    path = _manifest(tmp_path, {"issues": ["underexposure"]}, image="img.png")
    (tmp_path / "img.png").unlink()
    with pytest.raises(eval_analysis.ManifestError, match="image not found"):
        eval_analysis.load_manifest(path)


def test_load_manifest_rejects_missing_file(tmp_path: Path):
    with pytest.raises(eval_analysis.ManifestError, match="manifest not found"):
        eval_analysis.load_manifest(tmp_path / "missing.json")


def test_score_case_matches_sets_and_labels():
    expected = {
        "scene": {"primary": "portrait", "secondary": ["indoor"]},
        "subjects": ["person", "plant"],
        "lighting": {"direction": "side", "type": "natural"},
        "issues": ["underexposure", "highlight_clipping"],
    }
    predicted = {
        "scene": {"primary": "portrait", "secondary": ["indoor"], "confidence": 0.8},
        "subjects": [{"type": "person", "role": "primary"}],
        "lighting": {"direction": "side", "type": "artificial"},
        "issues": ["underexposure", "color_cast"],
    }
    scores = eval_analysis._score_case(expected, predicted)
    assert scores["scenePrimaryCorrect"] is True
    assert scores["sceneSecondaryExact"] is True
    assert scores["subjectTruePositives"] == 1
    assert scores["subjectExpectedCount"] == 2
    assert scores["lightingDirectionCorrect"] is True
    assert scores["lightingTypeCorrect"] is False
    assert scores["issueTruePositives"] == 1
    assert scores["issuePredictedCount"] == 2


def test_summarize_returns_null_when_a_metric_is_unlabeled():
    case = {
        "status": "completed",
        "isMock": True,
        "scores": {
            "scenePrimaryCorrect": True,
            "subjectExpectedCount": 1,
            "subjectPredictedCount": 1,
            "subjectTruePositives": 1,
        },
    }
    summary = eval_analysis.summarize([case], [0.5])
    assert summary["scenePrimaryAccuracy"] == 1.0
    assert summary["sceneSecondaryExactMatchAccuracy"] is None
    assert summary["lightingDirectionAccuracy"] is None
    assert summary["issueMicroPrecision"] is None
    assert summary["subjectMicroF1"] == 1.0
    assert summary["mock"]["allMock"] is True
    assert summary["latencySeconds"]["p95"] == 0.5


def test_f1_is_zero_when_precision_and_recall_are_zero():
    assert eval_analysis._f1(0.0, 0.0) == 0.0
    assert eval_analysis._f1(None, 0.5) is None
