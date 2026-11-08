#!/usr/bin/env python3
"""Measure Stage 3 analysis quality against a human-labeled manifest.

The script talks to a running FRAME AI API, uploads each labeled image, waits
for the analysis task to finish, and compares the report with the labels.
It never invents metrics: a missing manifest, missing image, or unreachable API
exits non-zero without printing a score.

Usage (from any directory):
    services/api/.venv/Scripts/python.exe scripts/eval_analysis.py \
        --manifest eval/manifest.json

Manifest schema and metric definitions live in docs/evaluation.md.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"completed", "failed"}
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
EXPECTED_FIELDS = {"scene", "subjects", "lighting", "issues"}


class ManifestError(ValueError):
    """Raised when the manifest or its dataset is incomplete."""


def _optional_text(value: object, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    return value.strip()


def _text_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ManifestError(f"{where} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _validate_expected(raw: object, case_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError(f"{case_id}: expected must be an object")
    unknown = set(raw) - EXPECTED_FIELDS
    if unknown:
        raise ManifestError(f"{case_id}: unsupported expected keys: {', '.join(sorted(unknown))}")

    expected: dict[str, Any] = {}

    scene = raw.get("scene")
    if scene is not None:
        if not isinstance(scene, dict):
            raise ManifestError(f"{case_id}: scene must be an object")
        unknown_scene = set(scene) - {"primary", "secondary"}
        if unknown_scene:
            raise ManifestError(
                f"{case_id}: unsupported scene keys: {', '.join(sorted(unknown_scene))}"
            )
        scene_labels: dict[str, Any] = {}
        primary = _optional_text(scene.get("primary"), f"{case_id}: scene.primary")
        if primary is not None:
            scene_labels["primary"] = primary
        if "secondary" in scene:
            scene_labels["secondary"] = _text_list(
                scene["secondary"], f"{case_id}: scene.secondary"
            )
        if scene_labels:
            expected["scene"] = scene_labels

    if "subjects" in raw:
        expected["subjects"] = _text_list(raw["subjects"], f"{case_id}: subjects")

    lighting = raw.get("lighting")
    if lighting is not None:
        if not isinstance(lighting, dict):
            raise ManifestError(f"{case_id}: lighting must be an object")
        unknown_lighting = set(lighting) - {"direction", "type"}
        if unknown_lighting:
            raise ManifestError(
                f"{case_id}: unsupported lighting keys: {', '.join(sorted(unknown_lighting))}"
            )
        lighting_labels: dict[str, str] = {}
        for key in ("direction", "type"):
            label = _optional_text(lighting.get(key), f"{case_id}: lighting.{key}")
            if label is not None:
                lighting_labels[key] = label
        if lighting_labels:
            expected["lighting"] = lighting_labels

    if "issues" in raw:
        expected["issues"] = _text_list(raw["issues"], f"{case_id}: issues")

    if not expected:
        raise ManifestError(f"{case_id}: expected must contain at least one label")
    return expected


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be an object")

    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ManifestError("manifest.cases must be a non-empty list")

    base_dir = path.resolve().parent
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ManifestError(f"case #{index}: must be an object")
        case_id = _optional_text(raw_case.get("id"), f"case #{index}: id")
        if case_id is None:
            raise ManifestError(f"case #{index}: id is required")
        if case_id in seen_ids:
            raise ManifestError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)

        image_name = _optional_text(raw_case.get("image"), f"{case_id}: image")
        if image_name is None:
            raise ManifestError(f"{case_id}: image is required")
        image_path = (base_dir / image_name).resolve()
        suffix = image_path.suffix.lower()
        if suffix not in CONTENT_TYPES:
            raise ManifestError(f"{case_id}: unsupported image extension {suffix or '(none)'}")
        if not image_path.is_file():
            raise ManifestError(f"{case_id}: image not found: {image_path}")

        cases.append(
            {
                "id": case_id,
                "image": image_name,
                "imagePath": image_path,
                "expected": _validate_expected(raw_case.get("expected"), case_id),
            }
        )

    dataset = data.get("dataset")
    version = data.get("version")
    return {
        "dataset": dataset if isinstance(dataset, str) else "unnamed",
        "version": version if isinstance(version, (str, int, float)) else None,
        "notes": data.get("notes") if isinstance(data.get("notes"), str) else None,
        "cases": cases,
    }


def _api_token() -> str | None:
    explicit = os.environ.get("FRAME_API_TOKEN_FILE")
    if explicit:
        candidate = Path(explicit)
    else:
        base = Path(os.environ.get("FRAME_DATA_DIR") or ROOT / "data")
        candidate = base / "api-token"
    try:
        token = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code", "unknown")
        message = error.get("message", "no message")
        return f"{code}: {message}"
    return f"HTTP {response.status_code}"


def _upload_image(client: httpx.Client, path: Path) -> str:
    content_type = CONTENT_TYPES[path.suffix.lower()]
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/images",
            files={"file": (path.name, handle, content_type)},
        )
    if response.status_code != 201:
        raise RuntimeError(f"upload failed ({_error_message(response)})")
    return str(response.json()["imageId"])


def _run_analysis(
    client: httpx.Client,
    image_id: str,
    timeout: float,
    poll_interval: float,
) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    created = client.post(
        "/api/v1/analysis",
        json={"imageId": image_id, "force": True},
    )
    if created.status_code != 202:
        raise RuntimeError(f"analysis create failed ({_error_message(created)})")
    analysis_id = str(created.json()["analysisId"])

    deadline = started + timeout
    status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analysis/{analysis_id}")
        if response.status_code != 200:
            raise RuntimeError(f"analysis poll failed ({_error_message(response)})")
        status = response.json()
        if status.get("status") in TERMINAL_STATUSES:
            return status, time.monotonic() - started
        time.sleep(poll_interval)
    raise TimeoutError(
        f"analysis {analysis_id} did not finish within {timeout:.1f}s "
        f"(last status: {status.get('status', 'unknown')})"
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[rank], 3)


def _predicted_summary(report: dict[str, Any]) -> dict[str, Any]:
    scene = report.get("scene") or {}
    lighting = report.get("lighting") or {}
    return {
        "scene": {
            "primary": scene.get("primary"),
            "secondary": list(scene.get("secondary") or []),
            "confidence": scene.get("confidence"),
        },
        "subjects": [
            {"type": subject.get("type"), "role": subject.get("role")}
            for subject in report.get("subjects") or []
        ],
        "lighting": {
            "direction": lighting.get("direction"),
            "type": lighting.get("type"),
        },
        "issues": [issue.get("type") for issue in report.get("issues") or []],
    }


def _score_case(expected: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, Any] = {}

    scene_expected = expected.get("scene")
    if scene_expected:
        if "primary" in scene_expected:
            scores["scenePrimaryCorrect"] = (
                predicted["scene"]["primary"] == scene_expected["primary"]
            )
        if "secondary" in scene_expected:
            scores["sceneSecondaryExact"] = set(predicted["scene"]["secondary"]) == set(
                scene_expected["secondary"]
            )

    if "subjects" in expected:
        expected_types = set(expected["subjects"])
        predicted_types = {subject["type"] for subject in predicted["subjects"] if subject["type"]}
        scores["subjectExpectedCount"] = len(expected_types)
        scores["subjectPredictedCount"] = len(predicted_types)
        scores["subjectTruePositives"] = len(expected_types & predicted_types)

    lighting_expected = expected.get("lighting")
    if lighting_expected:
        for key in ("direction", "type"):
            label = lighting_expected.get(key)
            if label is not None:
                scores[f"lighting{key.capitalize()}Correct"] = predicted["lighting"][key] == label

    if "issues" in expected:
        expected_types = set(expected["issues"])
        predicted_types = {issue for issue in predicted["issues"] if issue}
        scores["issueExpectedCount"] = len(expected_types)
        scores["issuePredictedCount"] = len(predicted_types)
        scores["issueTruePositives"] = len(expected_types & predicted_types)

    return scores


def summarize(case_results: list[dict[str, Any]], latencies: list[float]) -> dict[str, Any]:
    completed = [case for case in case_results if case["status"] == "completed"]

    def _accuracy(key: str) -> tuple[float | None, int]:
        values = [case["scores"][key] for case in completed if key in case.get("scores", {})]
        return _ratio(sum(1 for value in values if value), len(values)), len(values)

    subject_expected = 0
    subject_predicted = 0
    subject_true = 0
    issue_expected = 0
    issue_predicted = 0
    issue_true = 0
    for case in completed:
        scores = case.get("scores", {})
        subject_expected += scores.get("subjectExpectedCount", 0)
        subject_predicted += scores.get("subjectPredictedCount", 0)
        subject_true += scores.get("subjectTruePositives", 0)
        issue_expected += scores.get("issueExpectedCount", 0)
        issue_predicted += scores.get("issuePredictedCount", 0)
        issue_true += scores.get("issueTruePositives", 0)

    subject_precision = _ratio(subject_true, subject_predicted)
    subject_recall = _ratio(subject_true, subject_expected)
    issue_precision = _ratio(issue_true, issue_predicted)
    issue_recall = _ratio(issue_true, issue_expected)

    scene_primary, scene_primary_cases = _accuracy("scenePrimaryCorrect")
    scene_secondary, scene_secondary_cases = _accuracy("sceneSecondaryExact")
    lighting_direction, lighting_direction_cases = _accuracy("lightingDirectionCorrect")
    lighting_type, lighting_type_cases = _accuracy("lightingTypeCorrect")

    mock_values = [bool(case.get("isMock")) for case in completed if case.get("isMock") is not None]
    return {
        "cases": {
            "total": len(case_results),
            "completed": len(completed),
            "failed": len(case_results) - len(completed),
        },
        "scenePrimaryAccuracy": scene_primary,
        "scenePrimaryLabeledCases": scene_primary_cases,
        "sceneSecondaryExactMatchAccuracy": scene_secondary,
        "sceneSecondaryLabeledCases": scene_secondary_cases,
        "subjectMicroPrecision": subject_precision,
        "subjectMicroRecall": subject_recall,
        "subjectMicroF1": _f1(subject_precision, subject_recall),
        "lightingDirectionAccuracy": lighting_direction,
        "lightingDirectionLabeledCases": lighting_direction_cases,
        "lightingTypeAccuracy": lighting_type,
        "lightingTypeLabeledCases": lighting_type_cases,
        "issueMicroPrecision": issue_precision,
        "issueMicroRecall": issue_recall,
        "issueMicroF1": _f1(issue_precision, issue_recall),
        "latencySeconds": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "mock": {
            "allMock": bool(mock_values) and all(mock_values),
            "anyMock": any(mock_values),
            "mockCases": sum(1 for value in mock_values if value),
            "liveCases": sum(1 for value in mock_values if not value),
        },
    }


def run(
    manifest: dict[str, Any],
    api_url: str,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    latencies: list[float] = []

    with httpx.Client(base_url=api_url, timeout=60.0) as client:
        token = _api_token()
        if token is not None:
            client.headers["X-FRAME-Token"] = token
        try:
            health = client.get("/api/v1/health")
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"API is not reachable at {api_url}: {exc}. "
                "Start the API before running evaluation."
            ) from exc
        if health.status_code != 200:
            raise RuntimeError(f"API health check failed at {api_url} ({_error_message(health)})")

        for case in manifest["cases"]:
            result: dict[str, Any] = {
                "id": case["id"],
                "image": case["image"],
                "expected": case["expected"],
                "status": "failed",
            }
            try:
                image_id = _upload_image(client, case["imagePath"])
                status, latency = _run_analysis(
                    client, image_id, timeout=timeout, poll_interval=poll_interval
                )
                result["analysisId"] = status.get("analysisId")
                result["isMock"] = status.get("isMock")
                if status.get("status") != "completed":
                    error = status.get("error") or {}
                    result["error"] = {
                        "code": error.get("code", "analysis_failed"),
                        "message": error.get("message", "analysis failed"),
                    }
                else:
                    report = status.get("result")
                    if not isinstance(report, dict):
                        raise RuntimeError("completed task has no result payload")
                    predicted = _predicted_summary(report)
                    result["status"] = "completed"
                    result["latencySeconds"] = round(latency, 3)
                    result["predicted"] = predicted
                    result["scores"] = _score_case(case["expected"], predicted)
                    latencies.append(latency)
            except (httpx.HTTPError, RuntimeError, TimeoutError) as exc:
                result["error"] = {"code": "evaluation_error", "message": str(exc)}
            case_results.append(result)

    summary = summarize(case_results, latencies)
    warnings: list[str] = []
    if summary["mock"]["allMock"]:
        warnings.append("所有已完成结果均来自 Mock Provider，指标只验证流程，不代表真实模型质量。")
    elif summary["mock"]["anyMock"]:
        warnings.append("部分结果来自 Mock Provider，汇总指标混合了 Mock 与真实模型。")
    if summary["cases"]["failed"]:
        warnings.append(f"{summary['cases']['failed']} 个用例未完成，指标只基于已完成用例。")

    return {
        "dataset": manifest["dataset"],
        "datasetVersion": manifest["version"],
        "datasetNotes": manifest["notes"],
        "generatedAt": datetime.now(UTC).isoformat(),
        "apiUrl": api_url,
        "summary": summary,
        "warnings": warnings,
        "cases": case_results,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Evaluate Stage 3 analysis against a human-labeled manifest."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to manifest JSON (see docs/evaluation.md)",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-case analysis timeout in seconds",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Analysis status polling interval in seconds",
    )
    parser.add_argument("--output", type=Path, help="Write the JSON result here")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        result = run(
            manifest,
            api_url=args.api_url.rstrip("/"),
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
    except (ManifestError, RuntimeError) as exc:
        print(f"evaluation aborted: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["summary"]["cases"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
