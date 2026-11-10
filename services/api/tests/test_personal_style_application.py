from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_image, upload

PREFIX = "/api/v1/personal-styles"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        max_upload_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        allowed_origins="http://testserver",
        allowed_hosts="testserver",
        log_level="WARNING",
        api_auth_enabled=False,
        vision_provider="mock",
        decision_provider="mock",
        planner_provider="mock",
        mock_scenario="street",
        analysis_max_concurrency=1,
    )


@pytest.fixture
def application_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client


def _create_published_style(client: TestClient, *, name: str = "克制的城市") -> dict:
    parsed = client.post(
        f"{PREFIX}/custom/parse",
        json={
            "name": name,
            "description": "低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。",
            "avoid": "不要过饱和，高光不要溢出",
        },
    )
    assert parsed.status_code == 200, parsed.text
    saved = client.post(
        f"{PREFIX}/custom",
        json={"draft": parsed.json()["draft"]},
    )
    assert saved.status_code == 201, saved.text
    style_id = saved.json()["style"]["id"]
    published = client.post(
        f"{PREFIX}/{style_id}/status",
        json={"status": "published"},
    )
    assert published.status_code == 200, published.text
    return saved.json()


def _prepare_session(client: TestClient) -> tuple[str, str, str, dict]:
    uploaded = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert uploaded.status_code == 201, uploaded.text
    image_id = str(uploaded.json()["imageId"])
    session = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert session.status_code == 201, session.text
    session_id = str(session.json()["sessionId"])
    analysis_id = _analyze(client, image_id)
    return image_id, session_id, analysis_id, session.json()


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


def test_personal_style_fit_and_dynamic_plan(application_client: TestClient) -> None:
    client = application_client
    style = _create_published_style(client)
    style_id = style["style"]["id"]
    image_id, session_id, analysis_id, _ = _prepare_session(client)

    fit = client.get(f"/api/v1/styles/{style_id}/fit?image_id={image_id}")
    assert fit.status_code == 200, fit.text
    body = fit.json()
    assert body["styleKind"] == "personal"
    assert body["styleId"] == style_id
    assert body["overallScore"] >= 0
    assert body["dimensions"]

    plan = client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": style_id,
            "styleStrength": 0.9,
            "conversionMode": "style",
        },
    )
    assert plan.status_code == 200, plan.text
    plan_body = plan.json()
    assert plan_body["styleId"] == style_id
    assert plan_body["styleVersion"] == "1.0"
    assert plan_body["conversionMode"] == "style"
    adjustments = plan_body["recipe"]["adjustments"]
    assert adjustments["saturation"] < 0
    assert adjustments["temperature"] < 0


def test_personal_style_modes_are_distinguishable(application_client: TestClient) -> None:
    client = application_client
    style = _create_published_style(client, name="模式测试")
    style_id = style["style"]["id"]
    _, session_id, analysis_id, _ = _prepare_session(client)
    values: dict[str, float] = {}
    for mode in ("natural", "style", "creative"):
        plan = client.post(
            "/api/v1/ai/photographer/plan",
            json={
                "sessionId": session_id,
                "analysisId": analysis_id,
                "mode": "style",
                "styleId": style_id,
                "styleStrength": 0.9,
                "conversionMode": mode,
            },
        )
        assert plan.status_code == 200, plan.text
        values[mode] = plan.json()["recipe"]["adjustments"]["saturation"]
    assert values["natural"] > values["style"] >= values["creative"]


def test_locked_manual_fields_survive_generation(application_client: TestClient) -> None:
    client = application_client
    style = _create_published_style(client, name="锁定测试")
    style_id = style["style"]["id"]
    _, session_id, analysis_id, session = _prepare_session(client)
    base_revision_id = session["activeRevisionId"]
    recipe = session["revision"]["recipe"]
    recipe["adjustments"]["saturation"] = 7
    recipe["adjustments"]["temperature"] = 3
    revised = client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={
            "recipe": recipe,
            "parentRevisionId": base_revision_id,
            "source": "user",
        },
    )
    assert revised.status_code == 201, revised.text
    revised_id = revised.json()["activeRevisionId"]

    plan = client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": style_id,
            "styleStrength": 1.0,
            "conversionMode": "style",
            "lockedFields": ["saturation", "temperature"],
        },
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["baseRevisionId"] == revised_id
    assert body["recipe"]["adjustments"]["saturation"] == 7
    assert body["recipe"]["adjustments"]["temperature"] == 3
    assert any("锁定" in warning for warning in body["warnings"])

    unlocked = client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": style_id,
            "styleStrength": 1.0,
            "conversionMode": "style",
        },
    )
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["recipe"]["adjustments"]["saturation"] != 7


def test_personal_style_application_is_recorded_in_history(application_client: TestClient) -> None:
    client = application_client
    style = _create_published_style(client, name="历史测试")
    style_id = style["style"]["id"]
    _, session_id, analysis_id, session = _prepare_session(client)
    base_revision_id = session["activeRevisionId"]
    plan = client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": style_id,
            "styleStrength": 0.7,
            "conversionMode": "creative",
        },
    ).json()
    rendered = client.post(
        f"/api/v1/sessions/{session_id}/render",
        json={"recipe": plan["recipe"], "quality": "final"},
    )
    assert rendered.status_code == 200, rendered.text
    render_key = str(rendered.json()["previewUrl"]).rsplit("/", 1)[-1]

    accepted = client.post(
        f"/api/v1/ai/photographer/plan/{plan['planId']}/accept",
        json={"parentRevisionId": base_revision_id, "renderKey": render_key},
    )
    assert accepted.status_code == 200, accepted.text
    creation = accepted.json()["revision"]["creation"]
    assert creation["styleId"] == style_id
    assert creation["styleVersion"] == "1.0"
    assert creation["conversionMode"] == "creative"
    assert creation["styleStrength"] == 0.7
    assert creation["renderKey"] == render_key

    history = client.get(f"/api/v1/sessions/{session_id}/revisions").json()
    assert history["items"][0]["creation"]["styleId"] == style_id


def test_draft_and_foreign_personal_styles_are_not_resolvable(
    application_client: TestClient,
) -> None:
    client = application_client
    parsed = client.post(
        f"{PREFIX}/custom/parse",
        json={"name": "未发布", "description": "低饱和。"},
    ).json()
    saved = client.post(f"{PREFIX}/custom", json={"draft": parsed["draft"]})
    draft_id = saved.json()["style"]["id"]
    image_id, session_id, analysis_id, _ = _prepare_session(client)

    assert client.get(f"/api/v1/styles/{draft_id}/fit?image_id={image_id}").status_code == 404
    assert (
        client.post(
            "/api/v1/ai/photographer/plan",
            json={
                "sessionId": session_id,
                "analysisId": analysis_id,
                "mode": "style",
                "styleId": draft_id,
            },
        ).status_code
        == 404
    )
