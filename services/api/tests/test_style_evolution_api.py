from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

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
def client(tmp_path: Path):
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _style(client: TestClient, *, name: str, targets: dict[str, float] | None = None) -> str:
    payload: dict = {"name": name, "description": "测试个人风格。", "source": "photos"}
    if targets:
        payload["targets"] = targets
    created = client.post(PERSONAL, json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["style"]["id"])


def _feedback(
    client: TestClient,
    style_id: str,
    feedback_type: str,
    *,
    scope: str = "profile",
    note: str | None = None,
) -> dict:
    payload: dict = {"feedbackType": feedback_type, "scope": scope}
    if note is not None:
        payload["note"] = note
    response = client.post(f"{PERSONAL}/{style_id}/feedback", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client: TestClient, style_id: str, payload: dict | None = None) -> dict:
    response = client.post(f"{PERSONAL}/{style_id}/evolve/preview", json=payload or {})
    assert response.status_code == 200, response.text
    return response.json()


def test_feedback_defaults_to_single_edit(client: TestClient) -> None:
    style_id = _style(client, name="默认范围")
    response = client.post(
        f"{PERSONAL}/{style_id}/feedback",
        json={"feedbackType": "color_too_strong"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["scope"] == "single_edit"
    assert response.json()["appliedVersion"] is None


def test_all_nine_feedback_types_accepted(client: TestClient) -> None:
    style_id = _style(client, name="九种反馈")
    types = [
        "like_result",
        "dislike_result",
        "color_too_strong",
        "contrast_too_strong",
        "shadows_too_dark",
        "skin_unnatural",
        "style_subtle",
        "style_overdone",
        "keep_original",
    ]
    for feedback_type in types:
        body = _feedback(client, style_id, feedback_type)
        assert body["feedbackType"] == feedback_type
    listed = client.get(f"{PERSONAL}/{style_id}/feedback")
    assert listed.status_code == 200
    assert len(listed.json()["feedbacks"]) == 9


def test_invalid_feedback_type_rejected(client: TestClient) -> None:
    style_id = _style(client, name="非法反馈")
    response = client.post(
        f"{PERSONAL}/{style_id}/feedback",
        json={"feedbackType": "not_a_type"},
    )
    assert response.status_code == 422, response.text


def test_list_feedback_filters_by_scope(client: TestClient) -> None:
    style_id = _style(client, name="范围过滤")
    _feedback(client, style_id, "color_too_strong", scope="profile")
    _feedback(client, style_id, "contrast_too_strong", scope="single_edit")
    profile_only = client.get(f"{PERSONAL}/{style_id}/feedback?scope=profile")
    assert profile_only.status_code == 200
    assert len(profile_only.json()["feedbacks"]) == 1
    assert profile_only.json()["feedbacks"][0]["scope"] == "profile"


def test_preview_requires_profile_feedback(client: TestClient) -> None:
    style_id = _style(client, name="无反馈")
    response = client.post(f"{PERSONAL}/{style_id}/evolve/preview", json={})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "personal_style_feedback_required"


def test_preview_excludes_single_edit_feedback(client: TestClient) -> None:
    style_id = _style(client, name="区分范围", targets={"saturation": 20.0, "contrast": 15.0})
    _feedback(client, style_id, "color_too_strong", scope="profile")
    single = _feedback(client, style_id, "contrast_too_strong", scope="single_edit")
    body = _preview(client, style_id)
    assert body["feedbackCount"] == 1
    assert single["id"] not in body["evolution"]["feedbackIds"]
    # Single-edit contrast feedback must not lower the profile contrast.
    assert body["evolution"]["candidate"]["personal"]["targets"]["contrast"] == 15.0
    assert body["evolution"]["candidate"]["personal"]["targets"]["saturation"] == 16.0
    assert body["evolution"]["status"] == "proposed"
    assert body["evolution"]["newVersion"] is None
    assert body["changes"]
    assert body["adjustments"]


def test_preview_does_not_mutate_current_style(client: TestClient) -> None:
    style_id = _style(client, name="预览不修改", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    _preview(client, style_id)
    detail = client.get(f"{PERSONAL}/{style_id}")
    assert detail.json()["style"]["version"] == "1.0"
    assert detail.json()["style"]["personal"]["targets"]["saturation"] == 20.0


def test_preview_with_single_edit_id_rejected(client: TestClient) -> None:
    style_id = _style(client, name="显式单次")
    single = _feedback(client, style_id, "color_too_strong", scope="single_edit")
    response = client.post(
        f"{PERSONAL}/{style_id}/evolve/preview",
        json={"feedbackIds": [single["id"]]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "personal_style_feedback_scope"


def test_preview_with_unknown_feedback_id_rejected(client: TestClient) -> None:
    style_id = _style(client, name="未知反馈")
    _feedback(client, style_id, "color_too_strong")
    response = client.post(
        f"{PERSONAL}/{style_id}/evolve/preview",
        json={"feedbackIds": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert response.status_code == 404, response.text


def test_apply_requires_confirmation(client: TestClient) -> None:
    style_id = _style(client, name="需确认", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    evolution_id = body["evolution"]["id"]
    response = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply",
        json={"confirm": False},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "confirmation_required"
    detail = client.get(f"{PERSONAL}/{style_id}")
    assert detail.json()["style"]["version"] == "1.0"


def test_apply_creates_evolution_version_and_marks_feedback(client: TestClient) -> None:
    style_id = _style(client, name="确认演变", targets={"saturation": 20.0})
    feedback = _feedback(client, style_id, "color_too_strong", note="太艳了")
    body = _preview(client, style_id)
    evolution_id = body["evolution"]["id"]
    applied = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply",
        json={"confirm": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["style"]["version"] == "1.1"
    assert applied.json()["style"]["personal"]["targets"]["saturation"] == 16.0

    versions = client.get(f"{PERSONAL}/{style_id}/versions")
    assert versions.json()["versions"][0]["changeSource"] == "evolution"

    listed = client.get(f"{PERSONAL}/{style_id}/feedback?scope=profile")
    assert listed.json()["feedbacks"][0]["appliedVersion"] == "1.1"
    assert listed.json()["feedbacks"][0]["id"] == feedback["id"]

    evolutions = client.get(f"{PERSONAL}/{style_id}/evolutions")
    record = evolutions.json()["evolutions"][0]
    assert record["status"] == "confirmed"
    assert record["newVersion"] == "1.1"
    assert record["confirmedAt"] is not None
    assert record["baseVersion"] == "1.0"
    assert record["reason"]


def test_applied_feedback_cannot_be_deleted_or_reused(client: TestClient) -> None:
    style_id = _style(client, name="已应用反馈", targets={"saturation": 20.0})
    feedback = _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    client.post(
        f"{PERSONAL}/{style_id}/evolve/{body['evolution']['id']}/apply",
        json={"confirm": True},
    )
    deleted = client.delete(f"{PERSONAL}/{style_id}/feedback/{feedback['id']}")
    assert deleted.status_code == 409, deleted.text
    reused = client.post(
        f"{PERSONAL}/{style_id}/evolve/preview",
        json={"feedbackIds": [feedback["id"]]},
    )
    assert reused.status_code == 409, reused.text
    assert reused.json()["error"]["code"] == "personal_style_feedback_already_applied"


def test_unapplied_feedback_can_be_deleted(client: TestClient) -> None:
    style_id = _style(client, name="可删除反馈")
    feedback = _feedback(client, style_id, "color_too_strong")
    deleted = client.delete(f"{PERSONAL}/{style_id}/feedback/{feedback['id']}")
    assert deleted.status_code == 204, deleted.text
    listed = client.get(f"{PERSONAL}/{style_id}/feedback")
    assert listed.json()["feedbacks"] == []


def test_delete_unknown_feedback_returns_404(client: TestClient) -> None:
    style_id = _style(client, name="未知删除")
    response = client.delete(f"{PERSONAL}/{style_id}/feedback/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404, response.text


def test_apply_stale_proposal_after_style_change_conflicts(client: TestClient) -> None:
    style_id = _style(client, name="过期候选", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    evolution_id = body["evolution"]["id"]
    # User edits the style after previewing, advancing the head version.
    patched = client.patch(f"{PERSONAL}/{style_id}", json={"targets": {"saturation": 5.0}})
    assert patched.status_code == 200
    response = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply",
        json={"confirm": True},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "personal_style_version_conflict"


def test_apply_twice_conflicts(client: TestClient) -> None:
    style_id = _style(client, name="重复应用", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    evolution_id = body["evolution"]["id"]
    first = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply", json={"confirm": True}
    )
    assert first.status_code == 200
    second = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply", json={"confirm": True}
    )
    assert second.status_code == 409, second.text


def test_discard_proposal(client: TestClient) -> None:
    style_id = _style(client, name="丢弃候选", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    evolution_id = body["evolution"]["id"]
    discarded = client.post(f"{PERSONAL}/{style_id}/evolve/{evolution_id}/discard")
    assert discarded.status_code == 204, discarded.text
    evolutions = client.get(f"{PERSONAL}/{style_id}/evolutions")
    assert evolutions.json()["evolutions"][0]["status"] == "discarded"
    # A discarded proposal cannot be applied.
    applied = client.post(
        f"{PERSONAL}/{style_id}/evolve/{evolution_id}/apply", json={"confirm": True}
    )
    assert applied.status_code == 409, applied.text
    # Discarding again is rejected.
    again = client.post(f"{PERSONAL}/{style_id}/evolve/{evolution_id}/discard")
    assert again.status_code == 409, again.text


def test_historical_version_can_be_restored_after_evolution(client: TestClient) -> None:
    style_id = _style(client, name="可恢复", targets={"saturation": 20.0})
    _feedback(client, style_id, "color_too_strong")
    body = _preview(client, style_id)
    client.post(
        f"{PERSONAL}/{style_id}/evolve/{body['evolution']['id']}/apply",
        json={"confirm": True},
    )
    restored = client.post(f"{PERSONAL}/{style_id}/versions/1.0/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["style"]["version"] == "1.2"
    assert restored.json()["style"]["personal"]["targets"]["saturation"] == 20.0
    versions = client.get(f"{PERSONAL}/{style_id}/versions")
    assert versions.json()["versions"][0]["changeSource"] == "restore"


def test_unknown_style_returns_404(client: TestClient) -> None:
    response = client.post(
        f"{PERSONAL}/personal_missing00/feedback",
        json={"feedbackType": "color_too_strong", "scope": "profile"},
    )
    assert response.status_code == 404, response.text
    preview = client.post(f"{PERSONAL}/personal_missing00/evolve/preview", json={})
    assert preview.status_code == 404, preview.text
