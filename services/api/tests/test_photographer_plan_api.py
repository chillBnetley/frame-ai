from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.base import PatchRequest, PlannerRequest
from app.ai.contracts import AnalysisOptions
from app.ai.errors import ProviderError
from app.ai.prompts import PLANNER_PROMPT_VERSION
from app.core.config import Settings
from app.main import create_app
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.models.photographer import PatchDraft, PlannerDraft
from app.models.recipe import EditRecipe, recipe_hash
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.db import connect
from tests.conftest import image_row, make_image, upload


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


def _settings(tmp_path: Path, *, semantic_masks: bool = False) -> Settings:
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
        feature_semantic_masks=semantic_masks,
    )


@pytest.fixture
def plan_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def plan_client(plan_settings: Settings):
    with TestClient(create_app(plan_settings)) as client:
        yield client


def _prepare(client: TestClient, color: tuple[int, int, int] = (120, 80, 40)) -> tuple[str, str]:
    response = upload(client, make_image("PNG", (96, 64), color))
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


def _plan(client: TestClient, session_id: str, analysis_id: str | None = None) -> Any:
    payload: dict[str, str] = {"sessionId": session_id}
    if analysis_id is not None:
        payload["analysisId"] = analysis_id
    return client.post("/api/v1/ai/photographer/plan", json=payload)


def test_plan_returns_a_validated_recipe_and_persists_it(
    plan_client: TestClient,
    plan_settings: Settings,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = _plan(plan_client, session_id, analysis_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schemaVersion"] == "stage5/1"
    assert body["analysisId"] == analysis_id
    assert body["sessionId"] == session_id
    assert body["imageId"] == image_id
    assert body["mode"] == "auto"
    assert body["isMock"] is True
    assert body["degraded"] is False
    assert body["provider"]["name"] == "mock"
    assert body["provider"]["promptVersion"] == PLANNER_PROMPT_VERSION
    assert body["direction"]["id"]
    assert len(body["changes"]) <= 10
    assert all(change["evidenceRefs"] for change in body["changes"])

    recipe = EditRecipe.model_validate(body["recipe"])
    assert recipe.schema_version == "2.0"

    connection = connect(plan_settings.database_path)
    try:
        row = connection.execute(
            "SELECT * FROM photographer_plan WHERE id = ?",
            (body["planId"],),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["analysis_id"] == analysis_id
    assert row["session_id"] == session_id
    assert row["is_mock"] == 1
    assert row["degraded"] == 0
    assert row["recipe_hash"] == recipe_hash(recipe)
    stored_plan = json.loads(str(row["plan_json"]))
    assert stored_plan["planId"] == body["planId"]
    assert stored_plan["recipe"] == body["recipe"]


def test_plan_uses_the_latest_completed_analysis_when_none_is_supplied(
    plan_client: TestClient,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = _plan(plan_client, session_id)

    assert response.status_code == 200, response.text
    assert response.json()["analysisId"] == analysis_id


def test_plan_requires_a_completed_analysis(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)

    response = _plan(plan_client, session_id)

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "analysis_required"
    assert error["details"]["imageId"] == image_id


def test_plan_reports_a_pending_analysis_as_required(
    plan_client: TestClient,
    plan_settings: Settings,
):
    image_id, session_id = _prepare(plan_client)
    sha256 = str(image_row(plan_settings, image_id)["sha256"])
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
    SqliteAnalysisRepository(plan_settings.database_path).create(task)

    response = _plan(plan_client, session_id, task.id)

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "analysis_required"
    assert error["details"]["analysisId"] == task.id


def test_plan_rejects_an_analysis_from_another_image(plan_client: TestClient):
    first_image_id, _ = _prepare(plan_client, (120, 80, 40))
    first_analysis_id = _analyze(plan_client, first_image_id)
    _, second_session_id = _prepare(plan_client, (40, 80, 120))

    response = _plan(plan_client, second_session_id, first_analysis_id)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "image_analysis_mismatch"


def test_plan_rejects_an_unknown_analysis(plan_client: TestClient):
    _, session_id = _prepare(plan_client)

    response = _plan(plan_client, session_id, str(uuid4()))

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "analysis_not_found"


def test_plan_falls_back_to_deterministic_rules_on_invalid_model_output(
    plan_client: TestClient,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)
    plan_client.app.state.photographer_service.update_planner(
        FailingPlanner(ProviderError("planner_invalid_output", "bad json", retryable=False))
    )

    response = _plan(plan_client, session_id, analysis_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    assert body["isMock"] is False
    assert any("确定性规则方案" in warning for warning in body["warnings"])
    assert body["changes"]


def test_plan_maps_provider_timeout_without_falling_back(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)
    plan_client.app.state.photographer_service.update_planner(
        FailingPlanner(ProviderError("planner_provider_timeout", "slow", retryable=True))
    )

    response = _plan(plan_client, session_id, analysis_id)

    assert response.status_code == 504, response.text
    assert response.json()["error"]["code"] == "photographer_timeout"


def test_previewing_a_plan_does_not_write_history_and_accepting_uses_ai_source(
    plan_client: TestClient,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)
    session = plan_client.get(f"/api/v1/sessions/{session_id}").json()
    original_revision_id = session["activeRevisionId"]

    plan_response = _plan(plan_client, session_id, analysis_id)
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()

    before = plan_client.get(f"/api/v1/sessions/{session_id}/revisions").json()
    preview = plan_client.post(
        f"/api/v1/sessions/{session_id}/render",
        json={"recipe": plan["recipe"], "quality": "draft"},
    )
    assert preview.status_code == 200, preview.text
    after_preview = plan_client.get(f"/api/v1/sessions/{session_id}/revisions").json()
    assert after_preview["items"] == before["items"]
    assert plan_client.get(f"/api/v1/sessions/{session_id}").json()["activeRevisionId"] == (
        original_revision_id
    )

    accepted = plan_client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={
            "recipe": plan["recipe"],
            "parentRevisionId": original_revision_id,
            "source": "ai",
        },
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["revision"]["source"] == "ai"
    assert accepted_body["activeRevisionId"] != original_revision_id
    assert accepted_body["revision"]["recipe"] == plan["recipe"]

    undone = plan_client.post(f"/api/v1/sessions/{session_id}/undo", json={})
    assert undone.status_code == 200, undone.text
    assert undone.json()["activeRevisionId"] == original_revision_id


def test_plan_reports_the_selected_style_metadata(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": "monochrome",
            "styleStrength": 0.8,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "style"
    assert body["styleId"] == "monochrome"
    assert body["styleVersion"] == "1.0"
    assert body["styleStrength"] == 0.8
    assert body["direction"]["id"] == "monochrome_direction"
    assert body["recipe"]["styleId"] == "documentary"
    assert body["recipe"]["styleStrength"] == 80.0


def test_plan_omits_style_metadata_in_auto_mode(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    body = _plan(plan_client, session_id, analysis_id).json()

    assert body["styleId"] is None
    assert body["styleVersion"] is None
    assert body["styleStrength"] is None


def test_plan_rejects_a_style_that_is_not_available(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": "no_such_style",
        },
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "style_not_found"


def test_conversion_modes_endpoint_exposes_the_three_constraint_sets(plan_client: TestClient):
    response = plan_client.get("/api/v1/ai/photographer/conversion-modes")

    assert response.status_code == 200, response.text
    modes = response.json()["modes"]
    assert [item["mode"] for item in modes] == ["natural", "style", "creative"]
    for item in modes:
        assert item["allowedAdjustments"]
        assert any("生成式" in text for text in item["forbiddenOperations"])
        assert item["preservationConstraints"]
        assert (
            item["recommendedStrengthMin"]
            <= item["recommendedStrengthDefault"]
            <= item["recommendedStrengthMax"]
        )
    assert modes[0]["envelopeScale"] < modes[1]["envelopeScale"] < modes[2]["envelopeScale"]


def test_plan_applies_and_persists_the_conversion_mode(
    plan_client: TestClient,
    plan_settings: Settings,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)
    plans: dict[str, dict[str, Any]] = {}

    for mode in ("natural", "style", "creative"):
        response = plan_client.post(
            "/api/v1/ai/photographer/plan",
            json={
                "sessionId": session_id,
                "analysisId": analysis_id,
                "mode": "style",
                "styleId": "film",
                "styleStrength": 0.8,
                "conversionMode": mode,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversionMode"] == mode
        assert body["styleId"] == "film"
        assert body["styleStrength"] == 0.8
        plans[mode] = body

    natural_grain = plans["natural"]["recipe"]["adjustments"]["grain"]
    style_grain = plans["style"]["recipe"]["adjustments"]["grain"]
    creative_grain = plans["creative"]["recipe"]["adjustments"]["grain"]
    assert 0.0 <= natural_grain < style_grain < creative_grain
    assert plans["natural"]["recipe"] != plans["style"]["recipe"]
    assert plans["style"]["recipe"] != plans["creative"]["recipe"]

    connection = connect(plan_settings.database_path)
    try:
        row = connection.execute(
            "SELECT conversion_mode FROM photographer_plan WHERE id = ?",
            (plans["creative"]["planId"],),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["conversion_mode"] == "creative"


def test_plan_defaults_style_plans_to_the_neutral_conversion_mode(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": "film",
            "styleStrength": 0.8,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["conversionMode"] == "style"


def test_plan_rejects_a_conversion_mode_without_a_style(plan_client: TestClient):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "conversionMode": "creative",
        },
    )

    assert response.status_code == 422, response.text


def test_plan_resolves_seeded_master_and_genre_archives(
    plan_client: TestClient,
    plan_settings: Settings,
):
    image_id, session_id = _prepare(plan_client)
    analysis_id = _analyze(plan_client, image_id)

    response = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": "environmental_portrait",
            "styleStrength": 0.6,
            "conversionMode": "natural",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["styleId"] == "environmental_portrait"
    assert body["styleVersion"] == "1.0"
    assert body["conversionMode"] == "natural"
    assert body["provider"]["promptVersion"] == PLANNER_PROMPT_VERSION
    assert body["recipe"]["styleId"] == "portrait"
    assert body["recipe"]["styleStrength"] == 60.0
    assert any(change["path"].startswith("adjustments.") for change in body["changes"])
    assert body["recipe"]["masks"] == []
    assert any("语义蒙版不可用" in item for item in body["limitations"])

    connection = connect(plan_settings.database_path)
    try:
        connection.execute(
            "UPDATE style_profile SET enabled = 0 WHERE id = ?",
            ("environmental_portrait",),
        )
    finally:
        connection.close()
    disabled = plan_client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": "environmental_portrait",
        },
    )
    assert disabled.status_code == 404, disabled.text
    assert disabled.json()["error"]["code"] == "style_not_found"


def test_style_plan_with_semantic_mask_renders_and_tracks_the_ai_revision(tmp_path: Path):
    settings = _settings(tmp_path, semantic_masks=True)
    payload = make_image("PNG", (96, 64), (120, 80, 40))
    with TestClient(create_app(settings)) as client:
        uploaded = upload(client, payload)
        assert uploaded.status_code == 201, uploaded.text
        image_id = str(uploaded.json()["imageId"])
        session = client.post("/api/v1/sessions", json={"imageId": image_id})
        assert session.status_code == 201, session.text
        session_id = str(session.json()["sessionId"])
        original_revision_id = session.json()["activeRevisionId"]
        analysis_id = _analyze(client, image_id)

        plan_response = client.post(
            "/api/v1/ai/photographer/plan",
            json={
                "sessionId": session_id,
                "analysisId": analysis_id,
                "mode": "style",
                "styleId": "environmental_portrait",
                "styleStrength": 0.6,
                "conversionMode": "style",
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        semantic_masks = [mask for mask in plan["recipe"]["masks"] if mask["source"] == "semantic"]
        assert len(semantic_masks) == 1
        semantic_mask = semantic_masks[0]
        assert semantic_mask["semanticClass"] == "person"
        assert semantic_mask["matteId"]
        assert (settings.mattes_dir / f"{semantic_mask['matteId']}.png").is_file()
        assert any(
            item["maskId"] == semantic_mask["id"] for item in plan["recipe"]["localAdjustments"]
        )

        preview = client.post(
            f"/api/v1/sessions/{session_id}/render",
            json={"recipe": plan["recipe"], "quality": "draft"},
        )
        assert preview.status_code == 200, preview.text
        preview_image = client.get(str(preview.json()["previewUrl"]))
        assert preview_image.status_code == 200
        assert preview_image.content

        accepted = client.post(
            f"/api/v1/sessions/{session_id}/revisions",
            json={
                "recipe": plan["recipe"],
                "parentRevisionId": original_revision_id,
                "source": "ai",
            },
        )
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["revision"]["source"] == "ai"
        assert accepted.json()["revision"]["recipe"]["masks"] == plan["recipe"]["masks"]

        original = client.get(f"/api/v1/images/{image_id}/original")
        assert original.status_code == 200
        assert original.content == payload

        undone = client.post(f"/api/v1/sessions/{session_id}/undo", json={})
        assert undone.status_code == 200, undone.text
        assert undone.json()["activeRevisionId"] == original_revision_id

        connection = connect(settings.database_path)
        try:
            row = connection.execute(
                "SELECT analysis_id, style_id, style_version, conversion_mode "
                "FROM photographer_plan WHERE id = ?",
                (plan["planId"],),
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        assert row["analysis_id"] == analysis_id
        assert row["style_id"] == "environmental_portrait"
        assert row["style_version"] == "1.0"
        assert row["conversion_mode"] == "style"
