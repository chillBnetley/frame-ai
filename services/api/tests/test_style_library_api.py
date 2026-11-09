from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.style_profile import StyleProfile
from app.repositories.photographer_repo import (
    PhotographerPlanRecord,
    SqlitePhotographerPlanRepository,
)
from app.repositories.style_repo import SqliteStyleProfileRepository
from tests.conftest import make_image, upload

PREFIX = "/api/v1/styles"


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
def style_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def style_client(style_settings: Settings):
    with TestClient(create_app(style_settings)) as client:
        yield client


def _upload_image(client: TestClient) -> str:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201, response.text
    return str(response.json()["imageId"])


def _create_session(client: TestClient, image_id: str) -> str:
    response = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert response.status_code == 201, response.text
    return str(response.json()["sessionId"])


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


def _style_ids(client: TestClient, query: str = "") -> list[str]:
    response = client.get(f"{PREFIX}{query}")
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["styles"]]


def test_list_returns_the_seeded_archive_grouped_by_kind(style_client: TestClient) -> None:
    response = style_client.get(PREFIX)

    assert response.status_code == 200, response.text
    styles = response.json()["styles"]
    assert len(styles) == 16
    assert styles[0]["kind"] == "master"
    first = styles[0]
    assert first["category"] == "creative"
    assert len(first["signature"]) == 3
    assert first["suitableScenes"]
    assert first["favorite"] is False
    assert first["enabled"] is True

    masters = style_client.get(f"{PREFIX}?kind=master").json()["styles"]
    genres = style_client.get(f"{PREFIX}?kind=genre").json()["styles"]
    assert len(masters) == 8
    assert len(genres) == 8
    assert all(item["kind"] == "master" for item in masters)
    assert all(item["kind"] == "genre" and item["category"] == "scene" for item in genres)


def test_list_filters_by_scene_and_searches_name_or_id(style_client: TestClient) -> None:
    street = style_client.get(f"{PREFIX}?scene=street").json()["styles"]
    assert street
    assert all("street" in item["suitableScenes"] for item in street)
    assert {"saul_leiter", "fan_ho", "poetic_street"} <= {item["id"] for item in street}

    assert "fan_ho" in _style_ids(style_client, "?search=Fan")
    assert "fan_ho" in _style_ids(style_client, "?search=fan_ho")
    assert _style_ids(style_client, "?search=%25") == []
    assert _style_ids(style_client, "?search=不存在的风格") == []
    assert _style_ids(style_client, "?kind=genre&search=黑白") == ["bw_documentary"]


def test_detail_reads_current_and_archived_versions(style_settings: Settings) -> None:
    client = TestClient(create_app(style_settings))
    with client:
        current = client.get(f"{PREFIX}/fan_ho")
        assert current.status_code == 200, current.text
        body = current.json()
        assert body["style"]["id"] == "fan_ho"
        assert body["style"]["version"] == "1.0"
        assert body["style"]["philosophy"]
        assert body["favorite"] is False
        assert client.get(f"{PREFIX}/fan_ho/versions").json()["versions"] == ["1.0"]

        repository = SqliteStyleProfileRepository(style_settings.database_path)
        stored = repository.get("fan_ho")
        assert isinstance(stored, StyleProfile)
        revised = stored.model_copy(
            update={"version": "1.1", "description": "用户修订后的档案描述。"}
        )
        repository.add_version(revised)

        versions = client.get(f"{PREFIX}/fan_ho/versions").json()["versions"]
        assert versions == ["1.1", "1.0"]
        assert client.get(f"{PREFIX}/fan_ho").json()["style"]["version"] == "1.1"
        old = client.get(f"{PREFIX}/fan_ho?version=1.0").json()["style"]
        assert old["version"] == "1.0"
        assert old["description"] == stored.description
        assert (
            client.get(f"{PREFIX}/fan_ho?version=9.9").json()["error"]["code"] == "style_not_found"
        )

        missing = client.get(f"{PREFIX}/missing_style")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "style_not_found"
        assert client.get(f"{PREFIX}/Bad!").status_code == 422


def test_favorites_are_idempotent_and_listed_separately(style_client: TestClient) -> None:
    assert style_client.post(f"{PREFIX}/fan_ho/favorite").json() == {
        "styleId": "fan_ho",
        "favorite": True,
    }
    assert style_client.post(f"{PREFIX}/fan_ho/favorite").status_code == 200
    assert style_client.get(f"{PREFIX}/fan_ho").json()["favorite"] is True

    favorites = style_client.get(f"{PREFIX}/favorites").json()["styles"]
    assert [item["id"] for item in favorites] == ["fan_ho"]
    assert favorites[0]["favorite"] is True

    assert style_client.delete(f"{PREFIX}/fan_ho/favorite").json()["favorite"] is False
    assert style_client.delete(f"{PREFIX}/fan_ho/favorite").status_code == 200
    assert style_client.get(f"{PREFIX}/favorites").json()["styles"] == []

    for method in ("post", "delete"):
        response = getattr(style_client, method)(f"{PREFIX}/missing_style/favorite")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "style_not_found"


def test_enable_and_disable_hides_a_style_without_deleting_it(style_client: TestClient) -> None:
    disabled = style_client.post(f"{PREFIX}/fan_ho/enabled", json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"styleId": "fan_ho", "enabled": False}

    listed = [item["id"] for item in style_client.get(PREFIX).json()["styles"]]
    assert "fan_ho" not in listed
    assert len(listed) == 15
    everything = style_client.get(f"{PREFIX}?include_disabled=true").json()["styles"]
    assert len(everything) == 16
    hidden = next(item for item in everything if item["id"] == "fan_ho")
    assert hidden["enabled"] is False

    assert style_client.get(f"{PREFIX}/fan_ho").status_code == 404
    visible = style_client.get(f"{PREFIX}/fan_ho?include_disabled=true").json()["style"]
    assert visible["enabled"] is False
    archived = style_client.get(f"{PREFIX}/fan_ho?version=1.0&include_disabled=true").json()[
        "style"
    ]
    assert archived["enabled"] is False
    assert style_client.get(f"{PREFIX}/fan_ho/versions").status_code == 200

    missing = style_client.post(f"{PREFIX}/missing_style/enabled", json={"enabled": True})
    assert missing.status_code == 404

    enabled = style_client.post(f"{PREFIX}/fan_ho/enabled", json={"enabled": True})
    assert enabled.json() == {"styleId": "fan_ho", "enabled": True}
    assert len(style_client.get(PREFIX).json()["styles"]) == 16


def test_recommended_without_an_image_uses_the_library_basis(style_client: TestClient) -> None:
    response = style_client.get(f"{PREFIX}/recommended")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["basis"] == "library"
    assert body["scene"] is None
    assert len(body["styles"]) == 6
    assert body["styles"][0]["style"]["kind"] == "master"
    assert all(item["reason"] for item in body["styles"])
    assert all(item["style"]["enabled"] for item in body["styles"])

    assert len(style_client.get(f"{PREFIX}/recommended?limit=3").json()["styles"]) == 3
    assert style_client.get(f"{PREFIX}/recommended?limit=21").status_code == 422


def test_recommended_with_an_analysis_ranks_by_scene(style_client: TestClient) -> None:
    image_id = _upload_image(style_client)
    _analyze(style_client, image_id)

    response = style_client.get(f"{PREFIX}/recommended", params={"image_id": image_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["basis"] == "scene"
    assert body["scene"] == "portrait"
    assert body["styles"]
    assert all("portrait" in item["style"]["suitableScenes"] for item in body["styles"])
    assert all("人像" in item["reason"] for item in body["styles"])


def test_recommended_requires_a_completed_analysis_and_matching_report(
    style_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = _upload_image(style_client)
    missing = style_client.get(f"{PREFIX}/recommended", params={"image_id": image_id})
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "analysis_required"

    assert (
        style_client.get(f"{PREFIX}/recommended", params={"image_id": str(uuid4())}).json()[
            "error"
        ]["code"]
        == "image_not_found"
    )

    _analyze(style_client, image_id)
    other_id = _upload_image(style_client)
    analysis = style_client.app.state.analysis_task_service
    report = analysis.latest_completed(image_id)
    assert report is not None
    monkeypatch.setattr(analysis, "latest_completed", lambda _image_id: report)

    mismatch = style_client.get(f"{PREFIX}/recommended", params={"image_id": other_id})
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "image_analysis_mismatch"


def test_recent_lists_distinct_styles_in_last_used_order(style_client: TestClient) -> None:
    image_id = _upload_image(style_client)
    session_id = _create_session(style_client, image_id)
    analysis_id = _analyze(style_client, image_id)
    style_client.post(f"{PREFIX}/fan_ho/favorite")

    repository = SqlitePhotographerPlanRepository(style_client.app.state.settings.database_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def record(style_id: str, used_at: datetime) -> PhotographerPlanRecord:
        return PhotographerPlanRecord(
            id=str(uuid4()),
            image_id=image_id,
            session_id=session_id,
            analysis_id=analysis_id,
            mode="style",
            style_id=style_id,
            style_version="1.0",
            style_strength=0.5,
            provider="mock",
            model="mock",
            prompt_version="test",
            is_mock=True,
            degraded=False,
            confidence=0.5,
            plan_json="{}",
            recipe_json="{}",
            recipe_hash="0" * 64,
            created_at=used_at,
        )

    repository.create(record("bw_documentary", base))
    repository.create(record("fan_ho", base + timedelta(minutes=1)))
    repository.create(record("fan_ho", base + timedelta(minutes=2)))
    repository.create(record("portrait", base + timedelta(minutes=3)))
    repository.create(record("unknown_style", base + timedelta(minutes=4)))

    response = style_client.get(f"{PREFIX}/recent")

    assert response.status_code == 200, response.text
    styles = response.json()["styles"]
    assert [item["style"]["id"] for item in styles] == ["fan_ho", "bw_documentary"]
    assert styles[0]["style"]["favorite"] is True
    assert styles[0]["lastUsedAt"].startswith("2026-01-01T00:02:00")
    assert len(style_client.get(f"{PREFIX}/recent?limit=1").json()["styles"]) == 1

    style_client.post(f"{PREFIX}/bw_documentary/enabled", json={"enabled": False})
    recent = style_client.get(f"{PREFIX}/recent").json()["styles"]
    assert [item["style"]["id"] for item in recent] == ["fan_ho"]


def test_style_contract_uses_camel_case(style_client: TestClient) -> None:
    item: dict[str, Any] = style_client.get(PREFIX).json()["styles"][0]
    assert "suitableScenes" in item
    assert "defaultStrength" in item
    assert "engineStyle" in item
    assert "suitable_scenes" not in item
