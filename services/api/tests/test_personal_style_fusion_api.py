from __future__ import annotations

import time
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
        mock_scenario="street",
        analysis_max_concurrency=2,
    )


@pytest.fixture
def fusion_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _create_style(client: TestClient, *, name: str = "克制的城市") -> str:
    response = client.post(
        PREFIX,
        json={
            "name": name,
            "description": "低饱和的街头叙事。",
            "source": "photos",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["style"]["id"])


def _upload_images(client: TestClient, colors: list[tuple[int, int, int]]) -> list[str]:
    ids: list[str] = []
    for color in colors:
        response = upload(client, make_image("PNG", (96, 64), color))
        assert response.status_code == 201, response.text
        ids.append(str(response.json()["imageId"]))
    return ids


def _add_references(
    client: TestClient,
    style_id: str,
    image_ids: list[str],
) -> list[dict[str, object]]:
    response = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": image_ids, "consent": True},
    )
    assert response.status_code == 201, response.text
    return response.json()["references"]


def _analyze_all(client: TestClient, style_id: str) -> dict[str, object]:
    started = client.post(f"{PREFIX}/{style_id}/analyze", json={})
    assert started.status_code == 202, started.text
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        body = client.get(f"{PREFIX}/{style_id}/analysis").json()
        statuses = [item["status"] for item in body["references"]]
        assert "failed" not in statuses, body
        if statuses and all(status == "completed" for status in statuses):
            return body
        time.sleep(0.05)
    raise AssertionError("analysis timed out")


def _wait_for_reference(
    client: TestClient,
    style_id: str,
    reference_id: str,
    *,
    timeout: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"{PREFIX}/{style_id}/analysis").json()
        item = next(
            (entry for entry in body["references"] if entry["referenceId"] == reference_id),
            None,
        )
        assert item is not None, body
        assert item["status"] != "failed", body
        if item["status"] == "completed":
            return
        time.sleep(0.05)
    raise AssertionError("reference analysis timed out")


def test_fuse_saves_a_new_version_with_evidence(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    images = _upload_images(
        client,
        [(120, 80, 40), (40, 80, 120), (80, 120, 60)],
    )
    references = _add_references(client, style_id, images)
    _analyze_all(client, style_id)

    fused = client.post(f"{PREFIX}/{style_id}/fuse", json={})
    assert fused.status_code == 200, fused.text
    body = fused.json()

    assert body["version"] == "1.1"
    assert body["style"]["kind"] == "personal"
    assert body["style"]["personal"]["sampleCount"] == 3
    assert body["style"]["personal"]["confidence"] == body["confidence"]
    assert body["sampleCount"] == 3
    assert body["confidence"] > 0
    assert body["summary"]
    assert len(body["sections"]) == 6
    assert body["scenes"]
    assert len(body["contributions"]) == 3
    assert {item["referenceId"] for item in body["contributions"]} == {
        item["id"] for item in references
    }
    assert body["stability"].keys() == {"color", "tone", "light", "texture", "scene"}
    assert body["defaultStrength"] >= 0.35

    versions = client.get(f"{PREFIX}/{style_id}/versions").json()["versions"]
    assert [item["version"] for item in versions] == ["1.1", "1.0"]
    assert versions[0]["changeSource"] == "analysis"

    detail = client.get(f"{PREFIX}/{style_id}?version=1.1")
    assert detail.status_code == 200
    assert detail.json()["style"]["version"] == "1.1"

    again = client.post(f"{PREFIX}/{style_id}/fuse", json={"note": "补充参考照片"})
    assert again.status_code == 200, again.text
    assert again.json()["version"] == "1.2"


def test_fuse_requires_completed_analysis(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    image_id = _upload_images(client, [(120, 80, 40)])[0]
    _add_references(client, style_id, [image_id])

    response = client.post(f"{PREFIX}/{style_id}/fuse", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "personal_style_analysis_required"


def test_fuse_can_use_a_selected_subset(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    images = _upload_images(client, [(120, 80, 40), (40, 80, 120), (80, 120, 60)])
    references = _add_references(client, style_id, images)
    _analyze_all(client, style_id)

    response = client.post(
        f"{PREFIX}/{style_id}/fuse",
        json={"referenceIds": [references[0]["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sampleCount"] == 1
    assert len(body["contributions"]) == 1
    assert body["contributions"][0]["referenceId"] == references[0]["id"]


def test_fuse_rejects_an_unknown_reference(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    response = client.post(
        f"{PREFIX}/{style_id}/fuse",
        json={"referenceIds": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "personal_style_reference_not_found"


def test_fuse_preserves_user_confirmed_fields(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    updated = client.patch(
        f"{PREFIX}/{style_id}",
        json={
            "description": "我的个人描述。",
            "targets": {"saturation": -5.0},
            "traits": {"lightExpression": "我确认的自然侧光。"},
        },
    )
    assert updated.status_code == 200, updated.text
    image_id = _upload_images(client, [(120, 80, 40)])[0]
    _add_references(client, style_id, [image_id])
    _analyze_all(client, style_id)

    response = client.post(f"{PREFIX}/{style_id}/fuse", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["style"]["description"] == "我的个人描述。"
    assert body["style"]["personal"]["targets"] == {"saturation": -5.0}
    assert body["style"]["light"]["expression"] == "我确认的自然侧光。"
    assert body["definition"]["userOverrides"]["description"] == "我的个人描述。"
    assert body["definition"]["userOverrides"]["personal.targets"] == {"saturation": -5.0}
    assert body["definition"]["userOverrides"]["traits.light_expression"] == "我确认的自然侧光。"


def test_fuse_reports_references_without_features(fusion_client) -> None:
    client, _ = fusion_client
    style_id = _create_style(client)
    images = _upload_images(client, [(120, 80, 40), (40, 80, 120)])
    references = _add_references(client, style_id, images)
    started = client.post(
        f"{PREFIX}/{style_id}/analyze",
        json={"referenceIds": [references[0]["id"]]},
    )
    assert started.status_code == 202, started.text
    _wait_for_reference(client, style_id, str(references[0]["id"]))

    response = client.post(
        f"{PREFIX}/{style_id}/fuse",
        json={"referenceIds": [references[0]["id"], references[1]["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sampleCount"] == 1
    assert any("尚未完成分析" in limitation for limitation in body["limitations"])


def test_fusion_is_owner_scoped(fusion_client) -> None:
    client, settings = fusion_client
    repository = SqlitePersonalStyleRepository(settings.database_path)
    profile = build_default_personal_profile(
        style_id="personal_aaaabbbbcccc",
        name="别人的风格",
        description="不属于当前用户。",
        source=PersonalStyleSource.CUSTOM,
    )
    repository.create(profile, PersonalStyleDefinition(), owner_id="someone-else")

    response = client.post(f"{PREFIX}/{profile.id}/fuse", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "personal_style_not_found"
