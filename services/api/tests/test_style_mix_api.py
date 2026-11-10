from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_image, upload

PREFIX = "/api/v1/style-mixes"
PERSONAL = "/api/v1/personal-styles"


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
def mix_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client


def _personal_style(
    client: TestClient,
    *,
    name: str,
    targets: dict[str, float] | None = None,
    source: str = "photos",
) -> str:
    created = client.post(
        PERSONAL,
        json={"name": name, "description": "测试个人风格。", "source": source},
    )
    assert created.status_code == 201, created.text
    style_id = str(created.json()["style"]["id"])
    if targets:
        patched = client.patch(f"{PERSONAL}/{style_id}", json={"targets": targets})
        assert patched.status_code == 200, patched.text
    return style_id


def _custom_style(client: TestClient, *, name: str) -> str:
    parsed = client.post(
        f"{PERSONAL}/custom/parse",
        json={
            "name": name,
            "description": "低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。",
            "avoid": "不要过饱和，高光不要溢出",
        },
    )
    assert parsed.status_code == 200, parsed.text
    saved = client.post(f"{PERSONAL}/custom", json={"draft": parsed.json()["draft"]})
    assert saved.status_code == 201, saved.text
    return str(saved.json()["style"]["id"])


def _preview(client: TestClient, payload: dict) -> dict:
    response = client.post(f"{PREFIX}/preview", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_master_plus_master(mix_client: TestClient) -> None:
    client = mix_client
    body = _preview(
        client,
        {"styleA": {"styleId": "fan_ho"}, "styleB": {"styleId": "saul_leiter"}, "weight": 50},
    )
    assert body["profile"]["personal"]["source"] == "mixed"
    assert body["profile"]["kind"] == "personal"
    assert body["provenance"]["styleAId"] == "fan_ho"
    assert body["provenance"]["styleBId"] == "saul_leiter"
    assert body["provenance"]["styleAVersion"] == "1.0"
    assert "color.saturation" in {item["dimension"] for item in body["conflicts"]}
    assert body["protections"]
    assert len(body["dimensions"]) == 6


def test_preview_master_plus_personal(mix_client: TestClient) -> None:
    client = mix_client
    personal_id = _personal_style(client, name="我的色彩", targets={"saturation": 12.0})
    body = _preview(
        client,
        {
            "styleA": {"styleId": "fan_ho"},
            "styleB": {"styleId": personal_id},
            "weight": 40,
            "sources": {"color": "b", "tone": "a"},
        },
    )
    assert body["profile"]["personal"]["targets"]["saturation"] == 12.0
    color_plan = next(item for item in body["dimensions"] if item["dimension"] == "color")
    assert color_plan["source"] == "b"


def test_preview_personal_plus_custom(mix_client: TestClient) -> None:
    client = mix_client
    photos_id = _personal_style(client, name="照片风格", targets={"contrast": 10.0})
    custom_id = _custom_style(client, name="自定义风格")
    body = _preview(
        client,
        {"styleA": {"styleId": photos_id}, "styleB": {"styleId": custom_id}, "weight": 50},
    )
    assert body["profile"]["personal"]["source"] == "mixed"
    assert body["provenance"]["styleAId"] == photos_id
    assert body["provenance"]["styleBId"] == custom_id


def test_preview_two_personal_styles(mix_client: TestClient) -> None:
    client = mix_client
    a = _personal_style(client, name="风格甲", targets={"temperature": 10.0})
    b = _personal_style(client, name="风格乙", targets={"temperature": -10.0})
    body = _preview(
        client,
        {"styleA": {"styleId": a}, "styleB": {"styleId": b}, "weight": 50},
    )
    assert "color.temperature" in {item["dimension"] for item in body["conflicts"]}
    assert body["profile"]["personal"]["targets"].get("temperature", 0.0) == 0.0


def test_save_records_provenance_and_mix_version(mix_client: TestClient) -> None:
    client = mix_client
    personal_id = _personal_style(client, name="我的色彩", targets={"saturation": 12.0})
    saved = client.post(
        PREFIX,
        json={
            "styleA": {"styleId": "fan_ho"},
            "styleB": {"styleId": personal_id},
            "weight": 35,
            "sources": {"color": "b"},
            "name": "光影 × 我的色彩",
            "note": "确认混合",
        },
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    style_id = body["style"]["id"]
    assert body["source"] == "mixed"
    assert body["status"] == "draft"
    assert body["style"]["personal"]["source"] == "mixed"
    assert body["definition"]["userOverrides"]["mix"]["styleAId"] == "fan_ho"
    assert body["definition"]["userOverrides"]["mix"]["weight"] == 35

    versions = client.get(f"{PERSONAL}/{style_id}/versions")
    assert versions.status_code == 200, versions.text
    assert versions.json()["versions"][0]["changeSource"] == "mix"

    detail = client.get(f"{PERSONAL}/{style_id}")
    assert detail.status_code == 200
    assert detail.json()["definition"]["userOverrides"]["mix"]["sources"]["color"] == "b"


def test_save_name_conflict(mix_client: TestClient) -> None:
    client = mix_client
    _personal_style(client, name="重复名称")
    response = client.post(
        PREFIX,
        json={
            "styleA": {"styleId": "fan_ho"},
            "styleB": {"styleId": "saul_leiter"},
            "name": "重复名称",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "personal_style_name_conflict"


def test_unknown_source_returns_404(mix_client: TestClient) -> None:
    client = mix_client
    response = client.post(
        f"{PREFIX}/preview",
        json={"styleA": {"styleId": "fan_ho"}, "styleB": {"styleId": "personal_missing00"}},
    )
    assert response.status_code == 404, response.text


def test_same_style_returns_422(mix_client: TestClient) -> None:
    client = mix_client
    response = client.post(
        f"{PREFIX}/preview",
        json={"styleA": {"styleId": "fan_ho"}, "styleB": {"styleId": "fan_ho"}},
    )
    assert response.status_code == 422, response.text


def test_weight_bounds(mix_client: TestClient) -> None:
    client = mix_client
    for weight in (0, 100):
        body = _preview(
            client,
            {
                "styleA": {"styleId": "fan_ho"},
                "styleB": {"styleId": "saul_leiter"},
                "weight": weight,
            },
        )
        assert body["weight"] == weight
    response = client.post(
        f"{PREFIX}/preview",
        json={"styleA": {"styleId": "fan_ho"}, "styleB": {"styleId": "saul_leiter"}, "weight": 101},
    )
    assert response.status_code == 422, response.text


def _analyze(client: TestClient, image_id: str) -> str:
    created = client.post("/api/v1/analysis", json={"imageId": image_id})
    assert created.status_code == 202, created.text
    analysis_id = str(created.json()["analysisId"])
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/analysis/{analysis_id}")
        if status.json()["status"] in {"completed", "failed"}:
            assert status.json()["status"] == "completed", status.text
            return analysis_id
        time.sleep(0.05)
    raise AssertionError("analysis timed out")


def test_saved_mix_reapplies_to_a_new_photo(mix_client: TestClient) -> None:
    client = mix_client
    personal_id = _personal_style(client, name="我的色彩", targets={"saturation": -15.0})
    saved = client.post(
        PREFIX,
        json={
            "styleA": {"styleId": "saul_leiter"},
            "styleB": {"styleId": personal_id},
            "weight": 50,
            "sources": {"color": "b"},
            "name": "可复用混合",
        },
    )
    assert saved.status_code == 201, saved.text
    style_id = saved.json()["style"]["id"]
    published = client.post(f"{PERSONAL}/{style_id}/status", json={"status": "published"})
    assert published.status_code == 200, published.text

    uploaded = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert uploaded.status_code == 201, uploaded.text
    image_id = str(uploaded.json()["imageId"])
    session = client.post("/api/v1/sessions", json={"imageId": image_id})
    session_id = str(session.json()["sessionId"])
    analysis_id = _analyze(client, image_id)

    fit = client.get(f"/api/v1/styles/{style_id}/fit?image_id={image_id}")
    assert fit.status_code == 200, fit.text
    assert fit.json()["styleKind"] == "personal"

    plan = client.post(
        "/api/v1/ai/photographer/plan",
        json={
            "sessionId": session_id,
            "analysisId": analysis_id,
            "mode": "style",
            "styleId": style_id,
            "styleStrength": 0.8,
            "conversionMode": "style",
        },
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["styleId"] == style_id
    assert plan.json()["styleVersion"] == "1.0"
