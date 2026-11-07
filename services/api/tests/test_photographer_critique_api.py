from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.contracts import AnalysisOptions
from app.core.config import Settings
from app.main import create_app
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.db import connect
from tests.conftest import image_row, make_image, upload

_CRITIQUE_SECTIONS = (
    "measurements",
    "color",
    "lighting",
    "composition",
    "scene",
    "technicalQuality",
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
        vision_provider="mock",
        decision_provider="mock",
        mock_scenario="backlit",
        analysis_max_concurrency=1,
        analysis_max_attempts=2,
    )


@pytest.fixture
def critique_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def critique_client(critique_settings: Settings):
    with TestClient(create_app(critique_settings)) as client:
        yield client


def _prepare(client: TestClient) -> tuple[str, str]:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    session = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert session.status_code == 201, session.text
    return image_id, str(session.json()["sessionId"])


def _analyze(client: TestClient, image_id: str) -> str:
    created = client.post("/api/v1/analysis", json={"imageId": image_id})
    assert created.status_code == 202, created.text
    analysis_id = str(created.json()["analysisId"])
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/analysis/{analysis_id}")
        assert status.status_code == 200, status.text
        if status.json()["status"] in {"completed", "failed"}:
            assert status.json()["status"] == "completed", status.text
            return analysis_id
        time.sleep(0.05)
    raise AssertionError("analysis timed out")


def _report(client: TestClient, analysis_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/analysis/{analysis_id}/result")
    assert response.status_code == 200, response.text
    return response.json()


def _critique(client: TestClient, analysis_id: str, **payload: Any):
    return client.post(
        "/api/v1/ai/photographer/critique",
        json={"analysisId": analysis_id, **payload},
    )


def _apply(client: TestClient, session_id: str, patch: dict[str, Any], **payload: Any):
    return client.post(
        "/api/v1/ai/photographer/critique/apply",
        json={"sessionId": session_id, "patch": patch, **payload},
    )


def _session_recipe(client: TestClient, session_id: str) -> dict[str, Any]:
    return client.get(f"/api/v1/sessions/{session_id}").json()["revision"]["recipe"]


def _revisions(client: TestClient, session_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/sessions/{session_id}/revisions").json()


def _revise(client: TestClient, session_id: str, recipe: dict[str, Any]) -> dict[str, Any]:
    active = client.get(f"/api/v1/sessions/{session_id}").json()["activeRevisionId"]
    response = client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={"recipe": recipe, "parentRevisionId": active, "source": "user"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _plan_rows(settings: Settings) -> list[dict[str, Any]]:
    connection = connect(settings.database_path)
    try:
        rows = connection.execute("SELECT * FROM photographer_plan").fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _resolves(report: dict[str, Any], ref: str) -> bool:
    """A citation must be an identifier or a real leaf path inside the report."""
    identifiers = {issue["id"] for issue in report["issues"]}
    identifiers.update(region_id for issue in report["issues"] for region_id in issue["regionIds"])
    identifiers.update(region["id"] for region in report["regions"])
    identifiers.update(subject["id"] for subject in report["subjects"])
    identifiers.update(subject["regionId"] for subject in report["subjects"])
    if ref in identifiers:
        return True
    head, *path = ref.split(".")
    if head == "measurement":
        # The evidence-ref vocabulary says "measurement"; the report field is plural.
        head = "measurements"
    if head not in _CRITIQUE_SECTIONS:
        return False
    node: Any = report[head]
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return not isinstance(node, (list, dict))


def test_critique_describes_the_report_and_every_point_is_traceable(
    critique_client: TestClient,
):
    image_id, _session_id = _prepare(critique_client)
    analysis_id = _analyze(critique_client, image_id)
    report = _report(critique_client, analysis_id)

    response = _critique(critique_client, analysis_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysisId"] == analysis_id
    assert body["isMock"] is True
    assert body["generatedBy"] == "deterministic-rules"
    assert body["technical"]["objective"], "measured characteristics must always be listed"

    points = [
        *body["strengths"],
        *body["technical"]["objective"],
        *body["technical"]["possibleIssues"],
        *body["creative"],
    ]
    assert points
    for point in points:
        assert point["text"].strip()
        assert point["evidenceRefs"], point["text"]
        assert all(_resolves(report, ref) for ref in point["evidenceRefs"]), point
    for suggestion in body["suggestions"]:
        assert suggestion["category"]
        assert all(_resolves(report, ref) for ref in suggestion["evidenceRefs"]), suggestion
        patch = suggestion["recipePatch"]
        if patch is not None:
            assert any(value is not None for value in patch.values()), suggestion
    assert all(point["subjective"] is True for point in body["creative"])
    assert any("deterministic-rules" in note for note in body["limitations"])
    assert any("模拟视觉引擎" in note for note in body["limitations"])


def test_critique_only_names_subjects_the_analysis_detected(critique_client: TestClient):
    image_id, _session_id = _prepare(critique_client)
    analysis_id = _analyze(critique_client, image_id)
    report = _report(critique_client, analysis_id)
    detected = {subject["type"] for subject in report["subjects"]}
    detected.update(region["type"] for region in report["regions"])

    body = _critique(critique_client, analysis_id).json()

    nouns = {
        "person": "人物",
        "building": "建筑",
        "sky": "天空",
        "road": "道路",
        "plant": "植物",
        "animal": "动物",
        "food": "食物",
        "vehicle": "车辆",
    }
    text = " ".join(
        [
            *(point["text"] for key in ("strengths", "creative") for point in body[key]),
            *(point["text"] for point in body["technical"]["possibleIssues"]),
            *(item["text"] for item in body["suggestions"]),
        ]
    )
    for subject_type, noun in nouns.items():
        if subject_type not in detected:
            assert noun not in text, f"{noun} is not in the report"


def test_critique_requires_a_completed_analysis(
    critique_client: TestClient,
    critique_settings: Settings,
):
    image_id, _session_id = _prepare(critique_client)
    sha256 = str(image_row(critique_settings, image_id)["sha256"])
    now = datetime.now(UTC)
    task = AnalysisTaskRecord(
        id=str(uuid4()),
        image_id=image_id,
        image_sha256=sha256,
        options=AnalysisOptions(),
        config_key="pending-config",
        dedupe_key=uuid4().hex,
        status=TaskStatus.PENDING,
        stage=TaskStage.QUEUED,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    SqliteAnalysisRepository(critique_settings.database_path).create(task)

    response = _critique(critique_client, task.id)

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "analysis_required"
    assert error["details"]["analysisId"] == task.id


def test_critique_of_an_unknown_analysis_is_not_found(critique_client: TestClient):
    response = _critique(critique_client, str(uuid4()))
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "analysis_not_found"


def test_applying_a_suggestion_moves_only_its_own_parameters(
    critique_client: TestClient,
    critique_settings: Settings,
):
    image_id, session_id = _prepare(critique_client)
    analysis_id = _analyze(critique_client, image_id)
    current = _session_recipe(critique_client, session_id)
    edited = {
        **current,
        "adjustments": {
            **current["adjustments"],
            "contrast": 18.0,
            "crop": {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9},
        },
        "curve": {"master": [{"x": 0.3, "y": 0.24}, {"x": 0.7, "y": 0.78}]},
        "hsl": {"yellow": {"hue": -3.0, "saturation": 5.0, "luminance": 2.0}},
        "masks": [
            {
                "id": "mask_subject",
                "shape": "ellipse",
                "x": 0.4,
                "y": 0.4,
                "width": 0.3,
                "height": 0.4,
            }
        ],
    }
    _revise(critique_client, session_id, edited)
    committed = _session_recipe(critique_client, session_id)
    revisions_before = len(_revisions(critique_client, session_id))
    rows_before = _plan_rows(critique_settings)

    body = _critique(critique_client, analysis_id).json()
    actionable = [item for item in body["suggestions"] if item["recipePatch"]]
    assert actionable, "the backlit scenario should offer at least one parameter suggestion"
    suggestion = actionable[0]

    response = _apply(critique_client, session_id, suggestion["recipePatch"])

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changes"], "an actionable suggestion must produce a preview"
    assert all(change["path"].startswith("adjustments.") for change in result["changes"])
    patched = {field for field, value in suggestion["recipePatch"].items() if value is not None}
    assert {change["path"] for change in result["changes"]} <= {
        f"adjustments.{field}" for field in patched
    }
    assert patched, suggestion
    recipe = result["recipe"]
    assert recipe["curve"] == committed["curve"]
    assert recipe["hsl"] == committed["hsl"]
    assert recipe["masks"] == committed["masks"]
    assert recipe["localAdjustments"] == committed["localAdjustments"]
    assert recipe["adjustments"]["crop"] == committed["adjustments"]["crop"]
    assert recipe["adjustments"]["rotationDeg"] == committed["adjustments"]["rotationDeg"]
    assert recipe["output"] == committed["output"]
    assert {
        field: value for field, value in recipe["adjustments"].items() if field not in patched
    } == {field: value for field, value in committed["adjustments"].items() if field not in patched}

    # Applying is a preview only: nothing is saved and nothing is persisted.
    assert len(_revisions(critique_client, session_id)) == revisions_before
    assert _plan_rows(critique_settings) == rows_before
    assert _session_recipe(critique_client, session_id) == committed


def test_applying_clamps_a_patch_that_would_exceed_the_parameter_range(
    critique_client: TestClient,
):
    image_id, session_id = _prepare(critique_client)
    _analyze(critique_client, image_id)
    current = _session_recipe(critique_client, session_id)
    _revise(
        critique_client,
        session_id,
        {**current, "adjustments": {**current["adjustments"], "exposureEv": 4.0}},
    )

    response = _apply(critique_client, session_id, {"exposureEv": 5.0})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recipe"]["adjustments"]["exposureEv"] == 5.0
    assert body["changes"] == [
        {
            "path": "adjustments.exposureEv",
            "previous": 4.0,
            "proposed": 5.0,
            "reason": body["changes"][0]["reason"],
            "evidenceRefs": ["instruction"],
        }
    ]
    assert any("上下限" in warning for warning in body["warnings"])


def test_applying_rejects_a_patch_beyond_the_intent_bounds(critique_client: TestClient):
    image_id, session_id = _prepare(critique_client)
    _analyze(critique_client, image_id)

    response = _apply(critique_client, session_id, {"exposureEv": 9.0})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_applying_without_an_analysis_requires_one(critique_client: TestClient):
    _image_id, session_id = _prepare(critique_client)

    response = _apply(critique_client, session_id, {"contrast": 10.0})

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "analysis_required"
    assert error["details"]["imageId"] == _image_id


def test_applying_an_empty_patch_previews_no_changes(critique_client: TestClient):
    image_id, session_id = _prepare(critique_client)
    _analyze(critique_client, image_id)
    committed = _session_recipe(critique_client, session_id)

    response = _apply(critique_client, session_id, {})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changes"] == []
    assert body["recipe"] == committed
    assert any("未产生参数变化" in warning for warning in body["warnings"])


def test_critique_respects_preferences_when_sizing_a_suggestion(critique_client: TestClient):
    image_id, _session_id = _prepare(critique_client)
    analysis_id = _analyze(critique_client, image_id)

    default = _critique(critique_client, analysis_id).json()["suggestions"]
    gentle = _critique(
        critique_client,
        analysis_id,
        preferences={"naturalness": 1.0, "adjustmentStrength": 0.2},
    ).json()["suggestions"]

    assert [item["text"] for item in default] == [item["text"] for item in gentle]
    sized = {
        (index, field): value
        for index, item in enumerate(default)
        if item["recipePatch"]
        for field, value in item["recipePatch"].items()
        if value is not None
    }
    shrunk = {
        (index, field): value
        for index, item in enumerate(gentle)
        if item["recipePatch"]
        for field, value in item["recipePatch"].items()
        if value is not None
    }
    assert sized, "the scenario should propose at least one sized patch"
    assert shrunk.keys() <= sized.keys()
    for key, value in shrunk.items():
        assert abs(value) <= abs(sized[key])
