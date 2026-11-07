from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.base import PatchRequest, PlannerRequest
from app.ai.errors import ProviderError
from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.core.config import Settings
from app.main import create_app
from app.models.photographer import PatchDraft, PlannerDraft
from app.models.recipe import EditRecipe, recipe_hash
from app.repositories.db import connect
from tests.conftest import make_image, upload


class FailingPlanner:
    name = "failing"
    model = "failing-model"
    is_mock = False
    prompt_version = PLANNER_PROMPT_VERSION

    def __init__(self, error: ProviderError) -> None:
        self.error = error

    def plan(self, request: PlannerRequest) -> PlannerDraft:
        del request
        raise self.error

    def adjust(self, request: PatchRequest) -> PatchDraft:
        del request
        raise self.error

    def check_connection(self, *, timeout: float | None = None) -> int:
        del timeout
        raise self.error


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
def chat_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def chat_client(chat_settings: Settings):
    with TestClient(create_app(chat_settings)) as client:
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


def _chat(client: TestClient, plan_id: str, instruction: str, **payload: Any):
    return client.post(
        "/api/v1/ai/photographer/chat",
        json={"planId": plan_id, "instruction": instruction, **payload},
    )


def _session_recipe(client: TestClient, session_id: str) -> dict[str, Any]:
    return client.get(f"/api/v1/sessions/{session_id}").json()["revision"]["recipe"]


def _revise(
    client: TestClient,
    session_id: str,
    recipe: dict[str, Any],
    source: str = "user",
) -> dict[str, Any]:
    active = client.get(f"/api/v1/sessions/{session_id}").json()["activeRevisionId"]
    response = client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={"recipe": recipe, "parentRevisionId": active, "source": source},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _chat_rows(settings: Settings) -> list[dict[str, Any]]:
    connection = connect(settings.database_path)
    try:
        rows = connection.execute(
            "SELECT * FROM photographer_plan WHERE mode = 'chat' ORDER BY created_at"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _plan_and_analyse(client: TestClient) -> tuple[str, str, dict[str, Any]]:
    image_id, session_id = _prepare(client)
    analysis_id = _analyze(client, image_id)
    return image_id, session_id, _plan(client, session_id, analysis_id)


def test_chat_applies_a_minimal_patch_and_persists_a_chat_row(
    chat_client: TestClient,
    chat_settings: Settings,
):
    image_id, session_id, plan = _plan_and_analyse(chat_client)
    before = _session_recipe(chat_client, session_id)

    response = _chat(chat_client, plan["planId"], "降低饱和度")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemaVersion"] == "stage5/1"
    assert body["planId"] == plan["planId"]
    assert body["supported"] is True
    assert [change["path"] for change in body["changes"]] == ["adjustments.saturation"]
    assert all(change["evidenceRefs"] == ["instruction"] for change in body["changes"])
    recipe = EditRecipe.model_validate(body["recipe"])
    assert recipe.adjustments.saturation == -8.0
    assert recipe.curve == EditRecipe.model_validate(before).curve

    rows = _chat_rows(chat_settings)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == body["patchId"]
    assert row["mode"] == "chat"
    assert row["image_id"] == image_id
    assert row["session_id"] == session_id
    assert row["analysis_id"] == plan["analysisId"]
    assert row["style_id"] is None
    assert row["is_mock"] == 1
    assert row["degraded"] == 0
    assert row["recipe_hash"] == recipe_hash(recipe)
    assert json.loads(str(row["plan_json"]))["patchId"] == body["patchId"]


def test_chat_keeps_user_curves_hsl_masks_and_crop_and_edits_the_mask_only(
    chat_client: TestClient,
):
    _, session_id, plan = _plan_and_analyse(chat_client)
    current = _session_recipe(chat_client, session_id)
    edited = {
        **current,
        "adjustments": {
            **current["adjustments"],
            "contrast": 30.0,
            "crop": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
        },
        "curve": {"master": [{"x": 0.25, "y": 0.2}, {"x": 0.75, "y": 0.85}]},
        "hsl": {"orange": {"hue": 4.0, "saturation": -10.0, "luminance": 6.0}},
        "masks": [
            {
                "id": "mask_person",
                "shape": "rectangle",
                "x": 0.2,
                "y": 0.1,
                "width": 0.5,
                "height": 0.8,
            }
        ],
    }
    accepted = _revise(chat_client, session_id, edited)["revision"]
    assert accepted["source"] == "user"

    response = _chat(chat_client, plan["planId"], "让人物更突出")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["supported"] is True
    recipe = body["recipe"]
    assert recipe["curve"] == accepted["recipe"]["curve"]
    assert recipe["curve"]["master"] == edited["curve"]["master"]
    assert recipe["hsl"] == accepted["recipe"]["hsl"]
    assert recipe["hsl"]["orange"] == edited["hsl"]["orange"]
    assert recipe["masks"] == accepted["recipe"]["masks"]
    assert recipe["adjustments"]["crop"] == edited["adjustments"]["crop"]
    assert recipe["adjustments"]["contrast"] == 30.0
    assert [change["path"] for change in body["changes"]] == [
        "localAdjustments.mask_person.exposureEv",
        "localAdjustments.mask_person.shadows",
        "localAdjustments.mask_person.clarity",
    ]
    assert [item["maskId"] for item in recipe["localAdjustments"]] == ["mask_person"]


def test_chat_refuses_out_of_scope_instructions_with_an_unchanged_recipe(
    chat_client: TestClient,
):
    _, session_id, plan = _plan_and_analyse(chat_client)
    before = _session_recipe(chat_client, session_id)

    for instruction in ("删除画面里的人物", "扩图补齐边缘", "换背景到海边"):
        response = _chat(chat_client, plan["planId"], instruction)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["supported"] is False, instruction
        assert body["changes"] == []
        assert body["unsupported"]
        assert body["recipe"] == before


def test_chat_previews_only_until_the_user_accepts_it(chat_client: TestClient):
    _, session_id, plan = _plan_and_analyse(chat_client)
    original = chat_client.get(f"/api/v1/sessions/{session_id}").json()["activeRevisionId"]
    before = chat_client.get(f"/api/v1/sessions/{session_id}/revisions").json()

    response = _chat(chat_client, plan["planId"], "降低饱和度")
    assert response.status_code == 200, response.text
    patch = response.json()

    assert chat_client.get(f"/api/v1/sessions/{session_id}/revisions").json() == before
    assert chat_client.get(f"/api/v1/sessions/{session_id}").json()["activeRevisionId"] == (
        original
    )

    preview = chat_client.post(
        f"/api/v1/sessions/{session_id}/render",
        json={"recipe": patch["recipe"], "quality": "draft"},
    )
    assert preview.status_code == 200, preview.text

    accepted = _revise(chat_client, session_id, patch["recipe"], source="ai")
    assert accepted["revision"]["source"] == "ai"
    assert accepted["revision"]["recipe"] == patch["recipe"]


def test_each_turn_starts_from_the_recipe_the_previous_turn_produced(
    chat_client: TestClient,
    chat_settings: Settings,
):
    _, _, plan = _plan_and_analyse(chat_client)

    first = _chat(chat_client, plan["planId"], "降低饱和度").json()
    assert first["recipe"]["adjustments"]["saturation"] == -8.0

    # Nothing is saved in between: turn two continues turn one's recipe.
    second = _chat(chat_client, first["patchId"], "增加对比度")

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["planId"] == first["patchId"]
    assert body["patchId"] != first["patchId"]
    assert body["recipe"]["adjustments"]["saturation"] == -8.0
    assert {change["path"] for change in body["changes"]} == {"adjustments.contrast"}
    assert [row["mode"] for row in _chat_rows(chat_settings)] == ["chat", "chat"]


def test_chat_on_a_plan_anchor_edits_the_committed_recipe(chat_client: TestClient):
    """An unaccepted proposal stays a proposal; the next patch builds on the saved recipe."""
    _, session_id, plan = _plan_and_analyse(chat_client)
    committed = _session_recipe(chat_client, session_id)

    body = _chat(chat_client, plan["planId"], "降低饱和度").json()

    moved = {
        key
        for key, value in body["recipe"]["adjustments"].items()
        if committed["adjustments"][key] != value
    }
    assert moved == {"saturation"}
    assert [change["path"] for change in body["changes"]] == ["adjustments.saturation"]
    assert body["recipe"]["adjustments"]["saturation"] == -8.0
    assert body["recipe"]["curve"] == committed["curve"]
    assert body["recipe"]["masks"] == committed["masks"]


def test_chat_honours_the_preferences_sent_with_the_instruction(chat_client: TestClient):
    _, _, plan = _plan_and_analyse(chat_client)

    blocked = _chat(chat_client, plan["planId"], "加一点胶片颗粒").json()
    assert blocked["recipe"]["adjustments"]["grain"] == 0.0
    assert blocked["changes"] == []
    assert any("收紧" in warning for warning in blocked["warnings"])

    allowed = _chat(
        chat_client,
        plan["planId"],
        "加一点胶片颗粒",
        preferences={"allowStylization": True},
    ).json()
    assert allowed["recipe"]["adjustments"]["grain"] == 12.0
    assert [change["path"] for change in allowed["changes"]] == ["adjustments.grain"]


def test_chat_rejects_an_unknown_plan(chat_client: TestClient):
    response = _chat(chat_client, str(uuid4()), "降低饱和度")

    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "plan_not_found"


@pytest.mark.parametrize(
    ("instruction", "plan_id", "extra"),
    [
        ("", "0f9dd3a4-3f7f-4c1f-9b6a-2a1e5b6d0c11", {}),
        ("暗" * 501, "0f9dd3a4-3f7f-4c1f-9b6a-2a1e5b6d0c11", {}),
        ("降低饱和度", "not-a-uuid", {}),
        ("降低饱和度", "0f9dd3a4-3f7f-4c1f-9b6a-2a1e5b6d0c11", {"recipe": {}}),
    ],
)
def test_chat_validates_its_payload(
    chat_client: TestClient,
    instruction: str,
    plan_id: str,
    extra: dict[str, Any],
):
    response = _chat(chat_client, plan_id, instruction, **extra)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("code", "status", "error_code"),
    [
        ("planner_invalid_output", 502, "photographer_invalid_output"),
        ("planner_provider_timeout", 504, "photographer_timeout"),
        ("planner_provider_unavailable", 503, "photographer_unavailable"),
    ],
)
def test_chat_maps_provider_errors_without_falling_back(
    chat_client: TestClient,
    chat_settings: Settings,
    code: str,
    status: int,
    error_code: str,
):
    _, session_id, plan = _plan_and_analyse(chat_client)
    before = _session_recipe(chat_client, session_id)
    chat_client.app.state.photographer_service.update_planner(
        FailingPlanner(ProviderError(code, "unavailable", retryable=status != 502))
    )

    response = _chat(chat_client, plan["planId"], "降低饱和度")

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == error_code
    assert _chat_rows(chat_settings) == []
    assert _session_recipe(chat_client, session_id) == before


def test_chat_never_stores_or_logs_the_instruction(
    chat_client: TestClient,
    chat_settings: Settings,
    caplog: pytest.LogCaptureFixture,
):
    _, session_id, plan = _plan_and_analyse(chat_client)
    instruction = "降低饱和度到只剩灰色 SECRET-INSTRUCTION-TEXT"

    with caplog.at_level(logging.INFO, logger="frame_ai.photographer"):
        response = _chat(chat_client, plan["planId"], instruction)

    assert response.status_code == 200, response.text
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert instruction not in logged
    assert f"instruction_chars={len(instruction)}" in logged

    connection = connect(chat_settings.database_path)
    try:
        cursor = connection.execute("SELECT * FROM photographer_plan")
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
    finally:
        connection.close()
    assert rows
    for row in rows:
        for name, value in zip(columns, tuple(row), strict=True):
            assert instruction not in str(value), name
