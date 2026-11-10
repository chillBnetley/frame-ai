from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.personal_style import (
    PersonalStyleDefinition,
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.repositories.personal_style_repo import SqlitePersonalStyleRepository

PREFIX = "/api/v1/personal-styles"
DESCRIPTION = "低饱和、偏冷的环境色，保留暗部层次，人物肤色自然。"
AVOID = "不要过饱和，不要压黑，高光不要溢出"


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
    )


@pytest.fixture
def custom_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _parse(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post(
        f"{PREFIX}/custom/parse",
        json={
            "name": "克制的城市",
            "description": DESCRIPTION,
            "avoid": AVOID,
            "suitableScenes": [],
            **overrides,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_parse_returns_a_validated_structured_draft(custom_client) -> None:
    client, _ = custom_client
    body = _parse(client)
    draft = body["draft"]
    assert body["provider"]["isMock"] is True
    assert body["provider"]["promptVersion"] == "stage6.2-style-authoring/1"
    assert draft["suitableScenes"] == ["portrait"]
    assert draft["targets"]["saturation"] == -12
    assert draft["targets"]["temperature"] == -8
    assert "preserve_skin_tone" in draft["protected"]
    assert "preserve_highlight_detail" in draft["protected"]
    assert {"oversaturated", "crushed_blacks", "clipped_highlights"} <= set(draft["avoid"])
    assert draft["color"]["saturation"]
    assert draft["light"]["expression"]
    assert draft["texture"]["grain"]
    assert draft["summary"]
    assert "adjustments" not in draft
    assert "curve" not in draft
    assert draft["confidence"] > 0


def test_save_custom_style_creates_a_reusable_draft(custom_client) -> None:
    client, _ = custom_client
    draft = _parse(client)["draft"]
    response = client.post(
        f"{PREFIX}/custom",
        json={"draft": draft, "note": "由自然语言创建。"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "custom"
    assert body["status"] == "draft"
    assert body["style"]["version"] == "1.0"
    assert body["style"]["personal"]["targets"]["saturation"] == -12
    assert body["style"]["sceneFit"]["suitable"] == ["portrait"]
    assert "traits.light_expression" in body["style"]["personal"]["userOverrides"]
    assert "preserve_skin_tone" in body["style"]["constraints"]

    listed = client.get(PREFIX).json()["styles"]
    assert [item["id"] for item in listed] == [body["style"]["id"]]
    assert listed[0]["source"] == "custom"


def test_monochrome_description_keeps_a_monochrome_envelope(custom_client) -> None:
    client, _ = custom_client
    draft = _parse(
        client,
        name="黑白街头",
        description="黑白影调，高反差，重视光影层次，街头纪实。",
        avoid="",
    )["draft"]
    assert draft["targets"]["saturation"] == -100
    saved = client.post(f"{PREFIX}/custom", json={"draft": draft})
    assert saved.status_code == 201, saved.text
    profile = saved.json()["style"]
    assert profile["personal"]["targets"]["saturation"] == -100
    assert profile["envelope"]["saturation"] == 100


def test_refine_previews_changes_without_saving(custom_client) -> None:
    client, _ = custom_client
    draft = _parse(client)["draft"]
    saved = client.post(f"{PREFIX}/custom", json={"draft": draft}).json()
    style_id = saved["style"]["id"]
    before = saved["style"]["personal"]["targets"]

    refined = client.post(
        f"{PREFIX}/{style_id}/refine",
        json={"instruction": "更克制一点，保留更多高光，暗部不要太黑，肤色不要偏冷。"},
    )
    assert refined.status_code == 200, refined.text
    body = refined.json()
    change = body["draft"]
    assert body["currentVersion"] == "1.0"
    assert change["targets"]["saturation"] < before["saturation"]
    assert change["targets"]["highlights"] < 0
    assert change["targets"]["shadows"] > 0
    assert {
        "preserve_highlight_detail",
        "preserve_shadow_detail",
        "preserve_skin_tone",
    } <= set(change["protected"])
    assert change["light"]["highlights"] == "保留更多高光细节"

    unchanged = client.get(f"{PREFIX}/{style_id}").json()
    assert unchanged["style"]["version"] == "1.0"
    assert unchanged["style"]["personal"]["targets"] == before


def test_apply_refinement_creates_a_new_version(custom_client) -> None:
    client, _ = custom_client
    draft = _parse(client)["draft"]
    saved = client.post(f"{PREFIX}/custom", json={"draft": draft}).json()
    style_id = saved["style"]["id"]
    refined = client.post(
        f"{PREFIX}/{style_id}/refine",
        json={"instruction": "保留更多高光，暗部不要太黑。"},
    ).json()

    applied = client.post(
        f"{PREFIX}/{style_id}/refine/apply",
        json={"draft": refined["draft"], "note": "按反馈调整。"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["style"]["version"] == "1.1"
    assert body["style"]["personal"]["targets"]["highlights"] < 0
    assert body["style"]["personal"]["targets"]["shadows"] > 0
    versions = client.get(f"{PREFIX}/{style_id}/versions").json()["versions"]
    assert [item["version"] for item in versions] == ["1.1", "1.0"]
    assert versions[0]["changeSource"] == "user"
    assert versions[0]["changeNote"] == "按反馈调整。"


def test_unknown_instruction_keeps_the_style_and_warns(custom_client) -> None:
    client, _ = custom_client
    draft = _parse(client)["draft"]
    saved = client.post(f"{PREFIX}/custom", json={"draft": draft}).json()
    style_id = saved["style"]["id"]

    refined = client.post(
        f"{PREFIX}/{style_id}/refine",
        json={"instruction": "随便一点。"},
    )
    assert refined.status_code == 200, refined.text
    body = refined.json()["draft"]
    assert body["warnings"]
    assert body["confidence"] == 0.4
    assert body["targets"] == saved["style"]["personal"]["targets"]


def test_custom_style_endpoints_are_owner_scoped(custom_client) -> None:
    client, settings = custom_client
    repository = SqlitePersonalStyleRepository(settings.database_path)
    profile = build_default_personal_profile(
        style_id="personal_abcdef123456",
        name="别人的自定义风格",
        description="不属于当前用户。",
        source=PersonalStyleSource.CUSTOM,
    )
    repository.create(profile, PersonalStyleDefinition(), owner_id="someone-else")

    assert (
        client.post(
            f"{PREFIX}/{profile.id}/refine",
            json={"instruction": "更克制一点。"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{PREFIX}/{profile.id}/refine/apply",
            json={
                "draft": _parse(client)["draft"],
            },
        ).status_code
        == 404
    )
