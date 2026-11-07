from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.ai.providers.mock import MockPlannerProvider
from app.core.config import Settings
from app.main import create_app
from app.repositories.db import connect
from tests.conftest import make_image, upload


class StubRealPlanner:
    """A stand-in that reports is_mock=False. It is a stub, not a real provider."""

    name = "stub-real"
    model = "stub-real-model"
    is_mock = False
    prompt_version = PLANNER_PROMPT_VERSION

    def __init__(self) -> None:
        self._inner = MockPlannerProvider()

    def plan(self, request: Any) -> Any:
        return self._inner.plan(request)

    def adjust(self, request: Any) -> Any:
        return self._inner.adjust(request)

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        return 0


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
        mock_scenario="portrait",
        analysis_max_concurrency=1,
        analysis_max_attempts=2,
    )


@pytest.fixture
def feedback_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def feedback_client(feedback_settings: Settings):
    with TestClient(create_app(feedback_settings)) as client:
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


def _plan(client: TestClient, session_id: str, analysis_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/ai/photographer/plan",
        json={"sessionId": session_id, "analysisId": analysis_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _active_revision_id(client: TestClient, session_id: str) -> str:
    body = client.get(f"/api/v1/sessions/{session_id}").json()
    return str(body["activeRevisionId"])


def _revise(client: TestClient, session_id: str, recipe: dict[str, Any], source: str) -> str:
    response = client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={
            "recipe": recipe,
            "parentRevisionId": _active_revision_id(client, session_id),
            "source": source,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["activeRevisionId"])


def _bumped(recipe: dict[str, Any], value: float = 30.0) -> dict[str, Any]:
    edited: dict[str, Any] = dict(recipe)
    adjustments = dict(edited["adjustments"])
    adjustments["contrast"] = value
    edited["adjustments"] = adjustments
    return edited


def _feedback(client: TestClient, payload: dict[str, Any]):
    return client.post("/api/v1/ai/photographer/feedback", json=payload)


def _accepted_plan(client: TestClient, session_id: str, analysis_id: str) -> tuple[str, str]:
    """Run one plan and commit it as an 'ai' revision; return the plan and revision ids."""
    plan = _plan(client, session_id, analysis_id)
    revision_id = _revise(client, session_id, plan["recipe"], "ai")
    return str(plan["planId"]), revision_id


def test_accepting_a_plan_unchanged_is_recorded_as_accepted(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id, revision_id = _accepted_plan(feedback_client, session_id, analysis_id)

    response = _feedback(
        feedback_client,
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "plan",
            "planId": plan_id,
            "revisionId": revision_id,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "accepted"
    assert body["changedPaths"] == []
    assert (body["sessionId"], body["imageId"]) == (session_id, image_id)
    assert (body["planId"], body["revisionId"]) == (plan_id, revision_id)
    assert body["source"] == "plan"
    assert body["isMock"] is True, "the plan row was produced by the mock planner"
    assert body["degraded"] is False
    assert body["rubric"] is None

    listed = feedback_client.get(f"/api/v1/ai/photographer/feedback?sessionId={session_id}").json()
    assert [item["id"] for item in listed["items"]] == [body["id"]]
    assert listed["summary"]["accepted"] == 1
    assert listed["summary"]["total"] == 1


def test_editing_after_accepting_is_stored_as_modified_with_only_the_moved_parameter(
    feedback_client: TestClient,
):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan = _plan(feedback_client, session_id, analysis_id)
    _revise(feedback_client, session_id, plan["recipe"], "ai")

    final_recipe = _bumped(plan["recipe"], 42.0)
    drifted = _revise(feedback_client, session_id, final_recipe, "user")

    body = _feedback(
        feedback_client,
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "plan",
            "planId": plan["planId"],
            "revisionId": drifted,
        },
    ).json()

    assert body["action"] == "modified", "the stored recipe no longer matches the plan"
    assert body["changedPaths"] == ["adjustments.contrast"]

    summary = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_id}"
    ).json()["summary"]
    assert summary["modified"] == 1
    assert summary["accepted"] == 0
    assert [row["path"] for row in summary["changeFrequency"] if row["count"] > 0] == [
        "adjustments.contrast"
    ]


def test_rejecting_a_plan_leaves_the_history_alone(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    before = _active_revision_id(feedback_client, session_id)
    plan_id = _plan(feedback_client, session_id, analysis_id)["planId"]

    response = _feedback(
        feedback_client,
        {"sessionId": session_id, "action": "rejected", "source": "plan", "planId": plan_id},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "rejected"
    assert body["revisionId"] is None
    assert body["changedPaths"] == []
    assert _active_revision_id(feedback_client, session_id) == before, "rejection writes nothing"


def test_reset_is_compared_with_the_state_it_replaced(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    baseline = feedback_client.get(f"/api/v1/sessions/{session_id}").json()["revision"]["recipe"]

    moved = _revise(feedback_client, session_id, _bumped(baseline), "user")
    assert feedback_client.post(f"/api/v1/sessions/{session_id}/reset").status_code == 200
    after_reset = _active_revision_id(feedback_client, session_id)
    assert after_reset != moved

    body = _feedback(
        feedback_client,
        {"sessionId": session_id, "action": "reset", "revisionId": after_reset},
    ).json()

    assert body["action"] == "reset"
    assert body["planId"] is None
    assert body["source"] is None
    assert body["changedPaths"] == ["adjustments.contrast"], "measured against the pre-reset state"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"action": "modified"}, "modified is derived"),
        ({"action": "improved"}, "Input should be"),
        (
            {"action": "rejected", "revisionId": "0f9dd3a4-3f7f-4c1f-9b6a-2a1e5b6d0c11"},
            "revisionId",
        ),
        ({"action": "accepted", "notes": "天空太亮"}, "Extra input"),
        ({"action": "accepted", "instruction": "天空太亮"}, "Extra input"),
    ],
)
def test_the_feedback_request_only_accepts_observable_events(
    feedback_client: TestClient,
    payload: dict[str, Any],
    expected: str,
):
    _image_id, session_id = _prepare(feedback_client)

    response = _feedback(feedback_client, {"sessionId": session_id, **payload})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert expected in str(error["details"]["fields"][0]["message"])


def test_there_is_nowhere_to_store_prose(feedback_client: TestClient):
    schema = feedback_client.app.openapi()["components"]["schemas"]["PhotographerFeedbackRequest"]
    assert set(schema["properties"]) == {
        "sessionId",
        "action",
        "source",
        "planId",
        "revisionId",
        "rubric",
    }
    assert schema["additionalProperties"] is False


def test_only_the_scored_dimensions_come_back(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id, revision_id = _accepted_plan(feedback_client, session_id, analysis_id)

    body = _feedback(
        feedback_client,
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "plan",
            "planId": plan_id,
            "revisionId": revision_id,
            "rubric": {"exposure": 4, "naturalness": 2},
        },
    ).json()

    scores = {key: value for key, value in body["rubric"].items() if value is not None}
    assert scores == {"exposure": 4, "naturalness": 2}

    summary = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_id}"
    ).json()["summary"]
    assert summary["ratedCount"] == 1
    assert [
        (row["dimension"], row["average"], row["count"]) for row in summary["rubricAverages"]
    ] == [
        ("exposure", 4.0, 1),
        ("naturalness", 2.0, 1),
    ]


def test_a_rating_answers_with_the_row_it_annotates(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id, revision_id = _accepted_plan(feedback_client, session_id, analysis_id)

    anchor = {
        "sessionId": session_id,
        "action": "accepted",
        "source": "plan",
        "planId": plan_id,
        "revisionId": revision_id,
    }
    accepted = _feedback(feedback_client, anchor).json()
    rated = _feedback(feedback_client, {**anchor, "rubric": {"exposure": 5}}).json()

    assert rated["id"] == accepted["id"], "a score annotates the decision, it is not a second one"
    assert {key: value for key, value in rated["rubric"].items() if value is not None} == {
        "exposure": 5
    }

    listed = feedback_client.get(f"/api/v1/ai/photographer/feedback?sessionId={session_id}").json()
    assert [item["id"] for item in listed["items"]] == [accepted["id"]]
    summary = listed["summary"]
    assert (summary["total"], summary["accepted"], summary["ratedCount"]) == (1, 1, 1)


@pytest.mark.parametrize("score", [0, 6, -1, 5.5])
def test_scores_are_bounded_to_the_whole_one_to_five_scale(
    feedback_client: TestClient,
    score: float,
):
    _image_id, session_id = _prepare(feedback_client)

    response = _feedback(
        feedback_client,
        {"sessionId": session_id, "action": "reset", "rubric": {"exposure": score}},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_an_all_empty_rubric_is_not_counted_as_a_rating(feedback_client: TestClient):
    _image_id, session_id = _prepare(feedback_client)

    body = _feedback(
        feedback_client,
        {"sessionId": session_id, "action": "reset", "rubric": {"exposure": None}},
    ).json()

    summary = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_id}"
    ).json()["summary"]
    assert body["rubric"] is None
    assert summary["ratedCount"] == 0
    assert summary["rubricAverages"] == []


def test_the_summary_counts_behaviour_and_never_claims_quality(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id, revision_id = _accepted_plan(feedback_client, session_id, analysis_id)

    for payload in (
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "plan",
            "planId": plan_id,
            "revisionId": revision_id,
        },
        {"sessionId": session_id, "action": "rejected", "source": "plan", "planId": plan_id},
        {"sessionId": session_id, "action": "reset"},
    ):
        assert _feedback(feedback_client, payload).status_code == 200, payload

    listed = feedback_client.get(f"/api/v1/ai/photographer/feedback?sessionId={session_id}").json()
    summary = listed["summary"]

    assert listed["schemaVersion"] == "stage5/1"
    assert summary["total"] == 3
    assert (summary["accepted"], summary["rejected"], summary["modified"], summary["reset"]) == (
        1,
        1,
        0,
        1,
    )
    assert summary["bySource"] == {"plan": 2, "chat": 0, "critique": 0, "unset": 1}
    assert summary["mockCount"] == 3
    assert summary["realCount"] == 0
    for forbidden in ("improved", "qualityGain", "successRate", "averageScore", "better"):
        assert forbidden not in summary
    wording = " ".join(summary["disclaimers"])
    assert "用户行为" in wording
    for forbidden in ("质量提升", "变得更好", "improved", "better"):
        assert forbidden not in wording


def test_records_survive_reloading_and_can_be_filtered_and_limited(feedback_client: TestClient):
    image_a, session_a = _prepare(feedback_client)
    _image_b, session_b = _prepare(feedback_client)

    first = _feedback(feedback_client, {"sessionId": session_a, "action": "reset"}).json()["id"]
    second = _feedback(
        feedback_client, {"sessionId": session_a, "action": "rejected", "source": "critique"}
    ).json()["id"]
    other = _feedback(feedback_client, {"sessionId": session_b, "action": "reset"}).json()["id"]
    assert first and second and other

    by_session = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_a}"
    ).json()
    assert {item["id"] for item in by_session["items"]} == {first, second}
    assert by_session["summary"]["total"] == 2

    by_image = feedback_client.get(f"/api/v1/ai/photographer/feedback?imageId={image_a}").json()
    assert {item["id"] for item in by_image["items"]} == {first, second}

    by_plan = feedback_client.get(f"/api/v1/ai/photographer/feedback?planId={uuid4()}").json()
    assert by_plan["items"] == []
    assert by_plan["summary"]["total"] == 0

    limited = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_a}&limit=1"
    ).json()
    assert len(limited["items"]) == 1
    assert limited["summary"]["total"] == 2, "the summary covers the window, not the page"

    unknown = feedback_client.get("/api/v1/ai/photographer/feedback?limit=0")
    assert unknown.status_code == 422, unknown.text


def test_deleting_a_record_reports_no_content_and_removes_it(feedback_client: TestClient):
    _image_id, session_id = _prepare(feedback_client)
    feedback_id = _feedback(feedback_client, {"sessionId": session_id, "action": "reset"}).json()[
        "id"
    ]

    deleted = feedback_client.delete(f"/api/v1/ai/photographer/feedback/{feedback_id}")
    assert deleted.status_code == 204, deleted.text
    assert deleted.content == b""

    listed = feedback_client.get(f"/api/v1/ai/photographer/feedback?sessionId={session_id}").json()
    assert listed["items"] == []
    assert listed["summary"]["total"] == 0

    again = feedback_client.delete(f"/api/v1/ai/photographer/feedback/{feedback_id}")
    assert again.status_code == 404, again.text
    assert again.json()["error"]["code"] == "feedback_not_found"


def test_feedback_references_are_checked_against_the_session(feedback_client: TestClient):
    _image_id, session_id = _prepare(feedback_client)
    other_image, other_session = _prepare(feedback_client)
    other_analysis = _analyze(feedback_client, other_image)
    foreign_plan, foreign_revision = _accepted_plan(feedback_client, other_session, other_analysis)

    cases = (
        ({"sessionId": str(uuid4()), "action": "reset"}, 404, "session_not_found"),
        (
            {"sessionId": session_id, "action": "rejected", "planId": str(uuid4())},
            404,
            "plan_not_found",
        ),
        (
            {
                "sessionId": session_id,
                "action": "accepted",
                "planId": foreign_plan,
                "revisionId": foreign_revision,
            },
            409,
            "plan_session_mismatch",
        ),
        (
            {"sessionId": session_id, "action": "accepted", "revisionId": str(uuid4())},
            404,
            "revision_not_found",
        ),
    )
    for payload, status_code, code in cases:
        response = _feedback(feedback_client, payload)
        assert response.status_code == status_code, (payload, response.text)
        assert response.json()["error"]["code"] == code, response.text


def test_feedback_rows_leave_with_their_session(
    feedback_client: TestClient,
    feedback_settings: Settings,
):
    _image_id, session_id = _prepare(feedback_client)
    _other_image, other_session = _prepare(feedback_client)
    _feedback(feedback_client, {"sessionId": session_id, "action": "reset"})
    _feedback(feedback_client, {"sessionId": session_id, "action": "rejected"})
    keeper = _feedback(feedback_client, {"sessionId": other_session, "action": "reset"}).json()

    connection = connect(feedback_settings.database_path)
    try:
        connection.execute("DELETE FROM edit_session WHERE id = ?", (session_id,))
        rows = connection.execute("SELECT id FROM photographer_feedback").fetchall()
    finally:
        connection.close()

    assert [str(row[0]) for row in rows] == [keeper["id"]], "session deletion cascades"
    listed = feedback_client.get("/api/v1/ai/photographer/feedback").json()
    assert [item["id"] for item in listed["items"]] == [keeper["id"]]
    assert listed["summary"]["total"] == 1
    emptied = feedback_client.get(f"/api/v1/ai/photographer/feedback?sessionId={session_id}").json()
    assert emptied["items"] == []
    assert emptied["summary"]["total"] == 0


def test_mock_and_real_provenance_are_counted_apart(feedback_client: TestClient):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id, revision_id = _accepted_plan(feedback_client, session_id, analysis_id)

    mocked = _feedback(
        feedback_client,
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "plan",
            "planId": plan_id,
            "revisionId": revision_id,
        },
    ).json()
    assert mocked["isMock"] is True

    feedback_client.app.state.photographer_service.update_planner(StubRealPlanner())
    try:
        unmocked = _feedback(
            feedback_client, {"sessionId": session_id, "action": "reset", "revisionId": revision_id}
        ).json()
    finally:
        feedback_client.app.state.photographer_service.update_planner(MockPlannerProvider())

    assert unmocked["isMock"] is False, "the swapped-in double declares itself non-mock"
    summary = feedback_client.get(
        f"/api/v1/ai/photographer/feedback?sessionId={session_id}"
    ).json()["summary"]
    assert (summary["mockCount"], summary["realCount"]) == (1, 1)
    assert "模拟 Provider" in " ".join(summary["disclaimers"])


def test_instructions_never_reach_the_feedback_table(
    feedback_client: TestClient,
    feedback_settings: Settings,
):
    image_id, session_id = _prepare(feedback_client)
    analysis_id = _analyze(feedback_client, image_id)
    plan_id = _plan(feedback_client, session_id, analysis_id)["planId"]
    instruction = "把天空压暗并把肤色调暖一些"
    chat = feedback_client.post(
        "/api/v1/ai/photographer/chat",
        json={"planId": plan_id, "instruction": instruction},
    )
    assert chat.status_code == 200, chat.text
    chat_body = chat.json()
    revision_id = _revise(feedback_client, session_id, chat_body["recipe"], "ai")

    recorded = _feedback(
        feedback_client,
        {
            "sessionId": session_id,
            "action": "accepted",
            "source": "chat",
            "planId": chat_body["planId"],
            "revisionId": revision_id,
        },
    ).json()
    assert recorded["source"] == "chat"

    connection = connect(feedback_settings.database_path)
    try:
        rows = connection.execute("SELECT * FROM photographer_feedback").fetchall()
    finally:
        connection.close()
    assert len(rows) == 1
    for value in rows[0]:
        assert instruction not in str(value)
