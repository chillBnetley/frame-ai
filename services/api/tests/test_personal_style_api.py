from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.personal_style import (
    PersonalStyleDefinition,
    PersonalStyleSource,
    build_default_personal_profile,
)
from app.repositories.db import connect
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
    )


@pytest.fixture
def personal_client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        yield client, settings


def _create(
    client: TestClient,
    *,
    name: str = "克制的城市",
    source: str = "photos",
    **extra: object,
) -> dict[str, object]:
    response = client.post(
        f"{PREFIX}",
        json={"name": name, "description": "低饱和的街头叙事。", "source": source, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_image(client: TestClient) -> str:
    response = upload(client, make_image("PNG", (96, 64), (120, 80, 40)))
    assert response.status_code == 201, response.text
    return str(response.json()["imageId"])


def test_create_list_detail_and_versions(personal_client) -> None:
    client, _ = personal_client
    created = _create(client)
    style = created["style"]
    style_id = str(style["id"])

    assert re.fullmatch(r"personal_[a-z0-9]{6,32}", style_id)
    assert style["kind"] == "personal"
    assert style["version"] == "1.0"
    assert created["status"] == "draft"
    assert created["source"] == "photos"
    assert created["favorite"] is False
    assert created["references"] == []
    assert style["personal"]["confidence"] == 0.0

    listed = client.get(PREFIX).json()["styles"]
    assert [item["id"] for item in listed] == [style_id]
    assert listed[0]["referenceCount"] == 0

    updated = client.patch(
        f"{PREFIX}/{style_id}",
        json={
            "name": "克制的城市 II",
            "targets": {"saturation": -12.0, "contrast": 6.0},
            "avoid": ["oversaturated"],
            "traits": {
                "lightExpression": "自然柔和的侧光。",
                "textureGrain": "颗粒克制。",
            },
            "note": "降低饱和度。",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["style"]["version"] == "1.1"
    assert body["style"]["name"] == "克制的城市 II"
    assert body["style"]["personal"]["targets"] == {"saturation": -12.0, "contrast": 6.0}
    assert body["style"]["personal"]["avoid"] == ["oversaturated"]
    assert body["style"]["light"]["expression"] == "自然柔和的侧光。"
    assert body["style"]["texture"]["grain"] == "颗粒克制。"
    assert body["definition"]["userOverrides"]["personal.targets"] == {
        "saturation": -12.0,
        "contrast": 6.0,
    }
    assert body["definition"]["userOverrides"]["traits.light_expression"] == "自然柔和的侧光。"
    assert "traits.light_expression" in body["style"]["personal"]["userOverrides"]

    old = client.get(f"{PREFIX}/{style_id}?version=1.0")
    assert old.status_code == 200
    assert old.json()["style"]["name"] == "克制的城市"
    assert old.json()["style"]["personal"]["targets"] == {}

    versions = client.get(f"{PREFIX}/{style_id}/versions").json()["versions"]
    assert [item["version"] for item in versions] == ["1.1", "1.0"]
    assert versions[0]["changeSource"] == "user"

    compared = client.get(f"{PREFIX}/{style_id}/compare?from=1.0&to=1.1")
    assert compared.status_code == 200, compared.text
    paths = {item["path"] for item in compared.json()["changes"]}
    assert "profile.name" in paths
    assert "profile.personal.targets.saturation" in paths

    restored = client.post(f"{PREFIX}/{style_id}/versions/1.0/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["style"]["version"] == "1.2"
    assert restored.json()["style"]["name"] == "克制的城市"
    assert restored.json()["style"]["personal"]["targets"] == {}


def test_name_conflict_and_not_found(personal_client) -> None:
    client, _ = personal_client
    _create(client)
    conflict = client.post(
        PREFIX,
        json={"name": "克制的城市", "description": "另一个描述。", "source": "photos"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "personal_style_name_conflict"

    missing = client.get(f"{PREFIX}/personal_ffffffffffff")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "personal_style_not_found"
    assert client.get(f"{PREFIX}/Bad!").status_code == 422


def test_references_require_consent_and_enable_publishing(personal_client) -> None:
    client, _ = personal_client
    created = _create(client)
    style_id = str(created["style"]["id"])
    image_id = _upload_image(client)

    without_consent = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": False},
    )
    assert without_consent.status_code == 422

    added = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert added.status_code == 201, added.text
    references = added.json()["references"]
    assert len(references) == 1
    assert references[0]["imageId"] == image_id
    assert references[0]["status"] == "active"
    assert references[0]["consentScope"] == "analysis_only"
    assert references[0]["analysisId"] is None

    again = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert again.status_code == 201
    assert len(again.json()["references"]) == 1
    assert client.get(PREFIX).json()["styles"][0]["referenceCount"] == 1

    published = client.post(f"{PREFIX}/{style_id}/status", json={"status": "published"})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    removed = client.delete(f"{PREFIX}/{style_id}/references/{references[0]['id']}")
    assert removed.status_code == 204
    assert client.get(f"{PREFIX}/{style_id}/references").json()["references"] == []

    disabled = client.post(f"{PREFIX}/{style_id}/status", json={"status": "disabled"})
    assert disabled.status_code == 200
    blocked = client.post(f"{PREFIX}/{style_id}/status", json={"status": "published"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "personal_style_reference_required"


def test_reference_limit_is_enforced(personal_client, monkeypatch) -> None:
    import app.services.personal_style_service as personal_style_module

    monkeypatch.setattr(personal_style_module, "MAX_REFERENCES", 1)
    client, _ = personal_client
    created = _create(client)
    style_id = str(created["style"]["id"])
    first = _upload_image(client)
    second = _upload_image(client)

    assert (
        client.post(
            f"{PREFIX}/{style_id}/references",
            json={"imageIds": [first], "consent": True},
        ).status_code
        == 201
    )
    blocked = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [second], "consent": True},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "too_many_references"


def test_missing_image_is_rejected(personal_client) -> None:
    client, _ = personal_client
    created = _create(client)
    style_id = str(created["style"]["id"])
    response = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [str(uuid4())], "consent": True},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "image_not_found"


def test_custom_style_can_publish_without_references(personal_client) -> None:
    client, _ = personal_client
    created = _create(client, name="自然冷调", source="custom")
    style_id = str(created["style"]["id"])
    published = client.post(f"{PREFIX}/{style_id}/status", json={"status": "published"})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"


def test_delete_requires_confirmation_and_is_idempotent(personal_client) -> None:
    client, _ = personal_client
    created = _create(client)
    style_id = str(created["style"]["id"])

    blocked = client.delete(f"{PREFIX}/{style_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "confirmation_required"

    assert client.delete(f"{PREFIX}/{style_id}?confirm=true").status_code == 204
    assert client.delete(f"{PREFIX}/{style_id}?confirm=true").status_code == 204
    assert client.get(f"{PREFIX}/{style_id}").status_code == 404
    assert client.get(PREFIX).json()["styles"] == []


def test_owner_scope_hides_another_owners_style(personal_client) -> None:
    client, settings = personal_client
    repository = SqlitePersonalStyleRepository(settings.database_path)
    profile = build_default_personal_profile(
        style_id="personal_0123456789ab",
        name="别人的风格",
        description="不属于当前用户。",
        source=PersonalStyleSource.CUSTOM,
    )
    repository.create(profile, PersonalStyleDefinition(), owner_id="someone-else")

    assert client.get(PREFIX).json()["styles"] == []
    assert client.get(f"{PREFIX}/{profile.id}").status_code == 404
    assert client.patch(f"{PREFIX}/{profile.id}", json={"name": "改名"}).status_code == 404
    assert client.delete(f"{PREFIX}/{profile.id}?confirm=true").status_code == 404


def _insert_photo_feature(settings: Settings, style_id: str, reference_id: str) -> None:
    connection = connect(settings.database_path)
    try:
        connection.execute(
            "INSERT INTO personal_style_photo_feature "
            "(reference_id, style_id, image_sha256, analysis_id, extractor_version, "
            " features_json, confidence, is_mock, created_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', 0.8, 1, ?)",
            (
                reference_id,
                style_id,
                "a" * 64,
                str(uuid4()),
                "visual-dna/1",
                "2026-11-09T00:00:00Z",
            ),
        )
    finally:
        connection.close()


def test_revoking_consent_removes_features_and_keeps_style_and_original(
    personal_client,
) -> None:
    client, settings = personal_client
    created = _create(client, name="撤回授权的风格")
    style_id = str(created["style"]["id"])
    image_id = _upload_image(client)
    added = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert added.status_code == 201, added.text
    reference_id = str(added.json()["references"][0]["id"])
    _insert_photo_feature(settings, style_id, reference_id)

    revoked = client.delete(f"{PREFIX}/{style_id}/references/{reference_id}")
    assert revoked.status_code == 204

    assert client.get(f"{PREFIX}/{style_id}/references").json()["references"] == []
    assert client.get(f"{PREFIX}/{style_id}").status_code == 200
    assert client.get(f"/api/v1/images/{image_id}/original").status_code == 200

    connection = connect(settings.database_path)
    try:
        features = connection.execute(
            "SELECT COUNT(*) FROM personal_style_photo_feature WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert features == 0


def test_delete_cascades_every_related_row_and_keeps_the_original_image(
    personal_client,
) -> None:
    client, settings = personal_client
    removed = _create(client, name="待删除的风格")
    removed_id = str(removed["style"]["id"])
    kept = _create(client, name="保留的风格")
    kept_id = str(kept["style"]["id"])
    image_id = _upload_image(client)

    added = client.post(
        f"{PREFIX}/{removed_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert added.status_code == 201, added.text
    reference_id = str(added.json()["references"][0]["id"])
    _insert_photo_feature(settings, removed_id, reference_id)

    feedback = client.post(
        f"{PREFIX}/{removed_id}/feedback",
        json={"feedbackType": "color_too_strong", "scope": "profile"},
    )
    assert feedback.status_code == 201, feedback.text
    preview = client.post(f"{PREFIX}/{removed_id}/evolve/preview", json={})
    assert preview.status_code == 200, preview.text
    evolution_id = preview.json()["evolution"]["id"]
    applied = client.post(
        f"{PREFIX}/{removed_id}/evolve/{evolution_id}/apply",
        json={"confirm": True},
    )
    assert applied.status_code == 200, applied.text

    assert client.delete(f"{PREFIX}/{removed_id}?confirm=true").status_code == 204

    connection = connect(settings.database_path)
    try:
        style_rows = connection.execute(
            "SELECT COUNT(*) FROM personal_style WHERE id = ?", (removed_id,)
        ).fetchone()[0]
        related = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE style_id = ?", (removed_id,)
            ).fetchone()[0]
            for table in (
                "personal_style_version",
                "personal_style_reference",
                "personal_style_photo_feature",
                "personal_style_feedback",
                "personal_style_evolution",
            )
        }
        tombstone = connection.execute(
            "SELECT COUNT(*) FROM personal_style_tombstone WHERE style_id = ?",
            (removed_id,),
        ).fetchone()[0]
        image_rows = connection.execute(
            "SELECT COUNT(*) FROM image_asset WHERE id = ?", (image_id,)
        ).fetchone()[0]
        kept_rows = connection.execute(
            "SELECT COUNT(*) FROM personal_style WHERE id = ?", (kept_id,)
        ).fetchone()[0]
    finally:
        connection.close()

    assert style_rows == 0
    assert all(count == 0 for count in related.values())
    assert tombstone == 1
    assert image_rows == 1
    assert kept_rows == 1
    assert client.get(f"/api/v1/images/{image_id}/original").status_code == 200


def test_new_styles_stay_private_until_explicitly_published(personal_client) -> None:
    client, _ = personal_client
    created = _create(client, name="默认私有的风格", source="custom")
    style_id = str(created["style"]["id"])

    assert created["status"] == "draft"
    assert client.get(f"{PREFIX}?status=published").json()["styles"] == []
    drafts = client.get(f"{PREFIX}?status=draft").json()["styles"]
    assert [item["id"] for item in drafts] == [style_id]

    published = client.post(f"{PREFIX}/{style_id}/status", json={"status": "published"})
    assert published.status_code == 200, published.text
    listed = client.get(f"{PREFIX}?status=published").json()["styles"]
    assert [item["id"] for item in listed] == [style_id]


def test_deleting_an_image_marks_the_reference_missing(personal_client) -> None:
    client, _ = personal_client
    created = _create(client)
    style_id = str(created["style"]["id"])
    image_id = _upload_image(client)
    added = client.post(
        f"{PREFIX}/{style_id}/references",
        json={"imageIds": [image_id], "consent": True},
    )
    assert added.status_code == 201, added.text

    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204
    references = client.get(f"{PREFIX}/{style_id}/references").json()["references"]
    assert len(references) == 1
    assert references[0]["status"] == "missing"
    assert references[0]["imageId"] is None
    assert client.get(f"{PREFIX}/{style_id}").status_code == 200


def test_personal_styles_never_appear_in_the_public_library(personal_client) -> None:
    client, _ = personal_client
    created = _create(client, name="我的风格", source="custom")
    style_id = str(created["style"]["id"])
    client.post(f"{PREFIX}/{style_id}/status", json={"status": "published"})

    library = client.get("/api/v1/styles").json()["styles"]
    assert len(library) == 16
    assert all(not item["id"].startswith("personal_") for item in library)
    assert client.get(f"/api/v1/styles/{style_id}").status_code == 404
