from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.ai.contracts import AnalysisOptions
from app.core.config import Settings
from app.repositories.db import connect, utc_now
from app.tools.purge_orphans import apply_plan, build_plan
from tests.conftest import make_image, upload


def _upload_and_session(client: TestClient, payload: bytes | None = None) -> tuple[str, str]:
    response = upload(client, payload if payload is not None else make_image())
    assert response.status_code == 201, response.text
    image_id = str(response.json()["imageId"])
    created = client.post("/api/v1/sessions", json={"imageId": image_id})
    assert created.status_code == 201, created.text
    return image_id, str(created.json()["sessionId"])


def _commit(client: TestClient, session_id: str) -> None:
    state = client.get(f"/api/v1/sessions/{session_id}").json()
    response = client.post(
        f"/api/v1/sessions/{session_id}/revisions",
        json={
            "recipe": {"adjustments": {"exposureEv": 0.4}},
            "parentRevisionId": state["activeRevisionId"],
        },
    )
    assert response.status_code == 201, response.text


def _render(client: TestClient, session_id: str, *, max_edge: int | None = None) -> str:
    body: dict[str, object] = {
        "recipe": {"adjustments": {"exposureEv": 0.2}},
        "quality": "final",
    }
    if max_edge is not None:
        body["maxEdge"] = max_edge
    response = client.post(
        f"/api/v1/sessions/{session_id}/render",
        json=body,
    )
    assert response.status_code == 200, response.text
    return str(response.json()["previewUrl"])


def _counts(
    settings: Settings,
    table: str,
    where: str = "",
    params: tuple[object, ...] = (),
) -> int:
    connection = connect(settings.database_path)
    try:
        query = f"SELECT COUNT(*) FROM {table}"
        if where:
            query += f" WHERE {where}"
        return int(connection.execute(query, params).fetchone()[0])
    finally:
        connection.close()


def _insert_pending_analysis(settings: Settings, image_id: str) -> None:
    connection = connect(settings.database_path)
    try:
        row = connection.execute(
            "SELECT sha256 FROM image_asset WHERE id = ?",
            (image_id,),
        ).fetchone()
        assert row is not None
        now = utc_now()
        connection.execute(
            "INSERT INTO analysis_task "
            "(id, image_id, image_sha256, options_json, config_key, dedupe_key, "
            " status, stage, attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'config', ?, 'pending', 'queued', 0, ?, ?)",
            (
                str(uuid4()),
                image_id,
                str(row["sha256"]),
                AnalysisOptions().model_dump_json(by_alias=True),
                uuid4().hex,
                now,
                now,
            ),
        )
    finally:
        connection.close()


def _regular_files(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(
        path.name for path in directory.iterdir() if path.is_file() and not path.is_symlink()
    )


def test_delete_image_removes_rows_and_derivative_files(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client, make_image(size=(1000, 800)))
    _commit(client, session_id)
    preview_path = _render(client, session_id, max_edge=400)
    assert client.get(preview_path).status_code == 200
    original = settings.data_dir / "originals" / f"{image_id}.png"
    assert original.is_file()
    proxies = _regular_files(settings.preview_dir / "proxies")
    assert proxies

    response = client.delete(f"/api/v1/images/{image_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/v1/images/{image_id}/original").status_code == 404
    assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert _counts(settings, "image_asset") == 0
    assert _counts(settings, "edit_session") == 0
    assert _counts(settings, "edit_revision") == 0
    assert not original.exists()
    assert _regular_files(settings.preview_dir) == []
    assert _regular_files(settings.preview_dir / "proxies") == []

    # A repeated delete is still a success and must not resurrect anything.
    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204


def test_delete_session_keeps_the_original_and_cascades_revisions(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client)
    _commit(client, session_id)

    response = client.delete(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/sessions/{session_id}").status_code == 404
    assert client.get(f"/api/v1/images/{image_id}/original").status_code == 200
    assert _counts(settings, "image_asset") == 1
    assert _counts(settings, "edit_session") == 0
    assert _counts(settings, "edit_revision") == 0
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204


def test_delete_unknown_or_malformed_ids_are_404(client: TestClient):
    unknown = str(uuid4())
    image_response = client.delete(f"/api/v1/images/{unknown}")
    session_response = client.delete(f"/api/v1/sessions/{unknown}")
    malformed = client.delete("/api/v1/images/not-a-uuid")

    assert image_response.status_code == 404
    assert image_response.json()["error"]["code"] == "image_not_found"
    assert session_response.status_code == 404
    assert session_response.json()["error"]["code"] == "session_not_found"
    assert malformed.status_code == 404
    assert malformed.json()["error"]["code"] == "image_not_found"


def test_delete_image_is_rejected_while_analysis_is_active(
    client: TestClient,
    settings: Settings,
):
    image_id, _ = _upload_and_session(client)
    _insert_pending_analysis(settings, image_id)

    response = client.delete(f"/api/v1/images/{image_id}")

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "resource_busy"
    assert body["details"]["reasons"] == ["analysis"]
    assert _counts(settings, "image_asset") == 1


def test_delete_is_rejected_while_an_export_is_running(client: TestClient):
    image_id, session_id = _upload_and_session(client)
    exports = client.app.state.export_service

    exports._mark_active(session_id)
    try:
        session_response = client.delete(f"/api/v1/sessions/{session_id}")
        image_response = client.delete(f"/api/v1/images/{image_id}")
    finally:
        exports._mark_idle(session_id)

    assert session_response.status_code == 409
    assert session_response.json()["error"]["details"]["reasons"] == ["export"]
    assert image_response.status_code == 409
    assert image_response.json()["error"]["details"]["reasons"] == ["export"]
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204


def test_shared_content_keeps_the_proxy_until_the_last_image_is_deleted(
    client: TestClient,
    settings: Settings,
):
    payload = make_image(size=(640, 480), noise=True)
    first_image, first_session = _upload_and_session(client, payload)
    second_image, _ = _upload_and_session(client, payload)
    _render(client, first_session, max_edge=320)

    first_delete = client.delete(f"/api/v1/images/{first_image}")
    proxy_files = _regular_files(settings.preview_dir / "proxies")

    assert first_delete.status_code == 204
    assert proxy_files, "a shared source digest must keep its proxy cache"

    assert client.delete(f"/api/v1/images/{second_image}").status_code == 204
    assert _regular_files(settings.preview_dir / "proxies") == []


def test_delete_image_cascades_analysis_plans_and_feedback(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client)
    analysis_id = str(uuid4())
    plan_id = str(uuid4())
    now = utc_now()
    connection = connect(settings.database_path)
    try:
        image = connection.execute(
            "SELECT sha256 FROM image_asset WHERE id = ?", (image_id,)
        ).fetchone()
        assert image is not None
        revision = connection.execute(
            "SELECT active_revision_id FROM edit_session WHERE id = ?",
            (session_id,),
        ).fetchone()
        assert revision is not None
        connection.execute(
            "INSERT INTO analysis_task "
            "(id, image_id, image_sha256, options_json, config_key, dedupe_key, "
            " status, stage, attempts, created_at, updated_at, completed_at) "
            "VALUES (?, ?, ?, ?, 'config', ?, 'completed', 'completed', 1, ?, ?, ?)",
            (
                analysis_id,
                image_id,
                str(image["sha256"]),
                AnalysisOptions().model_dump_json(by_alias=True),
                uuid4().hex,
                now,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO analysis_result "
            "(id, task_id, schema_version, is_mock, report_json, created_at) "
            "VALUES (?, ?, '1.0', 1, '{}', ?)",
            (str(uuid4()), analysis_id, now),
        )
        connection.execute(
            "INSERT INTO photographer_plan "
            "(id, image_id, session_id, analysis_id, mode, provider, model, "
            " prompt_version, is_mock, plan_json, recipe_json, recipe_hash, created_at) "
            "VALUES (?, ?, ?, ?, 'auto', 'mock', 'mock', 'mock/1', 1, '{}', '{}', 'hash', ?)",
            (plan_id, image_id, session_id, analysis_id, now),
        )
        connection.execute(
            "INSERT INTO photographer_feedback "
            "(id, image_id, session_id, plan_id, revision_id, source, action, "
            " changed_paths_json, is_mock, degraded, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'plan', 'accepted', '[]', 1, 0, ?)",
            (
                str(uuid4()),
                image_id,
                session_id,
                plan_id,
                str(revision["active_revision_id"]),
                now,
            ),
        )
    finally:
        connection.close()

    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204

    for table in (
        "image_asset",
        "edit_session",
        "edit_revision",
        "analysis_task",
        "analysis_result",
        "photographer_plan",
        "photographer_feedback",
    ):
        assert _counts(settings, table) == 0, table


def test_purge_plan_is_dry_run_and_apply_removes_orphans(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client)
    _commit(client, session_id)
    originals = settings.data_dir / "originals"
    proxy_dir = settings.preview_dir / "proxies"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    orphan_original = originals / "orphan.png"
    orphan_original.write_bytes(b"orphan")
    orphan_proxy = proxy_dir / "deadbeef.png"
    orphan_proxy.write_bytes(b"orphan")
    # Simulate a crash between the database commit and file deletion.
    (originals / f"{image_id}.png").unlink()

    plan = build_plan(settings)

    assert plan.orphan_originals == (orphan_original,)
    assert plan.orphan_proxies == (orphan_proxy,)
    assert plan.dangling_images == (image_id,)
    assert orphan_original.exists() and orphan_proxy.exists()

    report = apply_plan(settings, plan)

    assert report.deleted_originals == 1
    assert report.deleted_proxies == 1
    assert report.deleted_records == 1
    assert not orphan_original.exists()
    assert not orphan_proxy.exists()
    assert _counts(settings, "image_asset", "id = ?", (image_id,)) == 0
    assert _counts(settings, "edit_session", "id = ?", (session_id,)) == 0
    assert _counts(settings, "edit_revision") == 0


def test_purge_plan_treats_proxies_of_dangling_images_as_orphans(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client, make_image(size=(640, 480), noise=True))
    _render(client, session_id, max_edge=320)
    proxy_dir = settings.preview_dir / "proxies"
    proxy_files = _regular_files(proxy_dir)
    assert proxy_files
    (settings.data_dir / "originals" / f"{image_id}.png").unlink()

    plan = build_plan(settings)

    assert plan.dangling_images == (image_id,)
    expected = tuple(sorted(proxy_dir / name for name in proxy_files))
    assert plan.orphan_proxies == expected

    report = apply_plan(settings, plan)

    assert report.deleted_proxies == len(expected)
    assert _regular_files(proxy_dir) == []
    assert _counts(settings, "image_asset", "id = ?", (image_id,)) == 0


def test_purge_keeps_proxies_of_live_images(client: TestClient, settings: Settings):
    _, session_id = _upload_and_session(client)
    _render(client, session_id)

    plan = build_plan(settings)

    assert plan.orphan_proxies == ()
    assert plan.orphan_originals == ()
    assert plan.dangling_images == ()


def _accept_generative_edit(client: TestClient, session_id: str) -> dict[str, object]:
    import time

    mask = client.post(
        "/api/v1/generative/masks",
        json={
            "sessionId": session_id,
            "kind": "rect",
            "definition": {"region": {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}},
        },
    )
    assert mask.status_code == 201, mask.text
    created = client.post(
        "/api/v1/generative/tasks",
        json={
            "sessionId": session_id,
            "taskType": "local_edit",
            "instruction": "deletion lifecycle",
            "maskId": mask.json()["maskId"],
            "params": {"candidates": 1},
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["taskId"]
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        payload = client.get(f"/api/v1/generative/tasks/{task_id}").json()
        if payload["status"] in {"succeeded", "failed", "cancelled", "expired"}:
            break
        time.sleep(0.02)
    assert payload["status"] == "succeeded", payload
    result = payload["results"][0]
    accepted = client.post(f"/api/v1/generative/results/{result['resultId']}/accept")
    assert accepted.status_code == 200, accepted.text
    return {"maskId": mask.json()["maskId"], "resultId": result["resultId"]}


def test_deleting_a_session_removes_its_generated_assets(
    client: TestClient,
    settings: Settings,
):
    image_id, session_id = _upload_and_session(client)
    _accept_generative_edit(client, session_id)
    # A mask created after acceptance is bound to the generated asset and must
    # leave with it; the first mask belongs to the original image-level base.
    bound_mask = client.post(
        "/api/v1/generative/masks",
        json={
            "sessionId": session_id,
            "kind": "rect",
            "definition": {"region": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}},
        },
    )
    assert bound_mask.status_code == 201, bound_mask.text
    assert bound_mask.json()["baseGeneratedAssetId"] is not None

    connection = connect(settings.database_path)
    try:
        generated = connection.execute("SELECT storage_key FROM generated_asset").fetchall()
        bound_key = connection.execute(
            "SELECT storage_key FROM generative_mask WHERE base_generated_asset_id IS NOT NULL"
        ).fetchone()["storage_key"]
    finally:
        connection.close()
    assert generated
    generated_paths = [settings.data_dir / str(row["storage_key"]) for row in generated]
    assert all(path.is_file() for path in generated_paths)
    bound_mask_path = settings.data_dir / str(bound_key)
    assert bound_mask_path.is_file()

    deleted = client.delete(f"/api/v1/sessions/{session_id}")

    assert deleted.status_code == 204, deleted.text
    assert all(not path.exists() for path in generated_paths)
    assert not bound_mask_path.exists()
    assert _counts(settings, "generated_asset") == 0
    assert _counts(settings, "generative_task") == 0
    assert _counts(settings, "generative_result") == 0
    # The image-level mask made against the original is still used by the
    # surviving image, so only the generated-asset mask above was removed.
    remaining = _counts(settings, "generative_mask")
    assert remaining == 1
    assert _counts(settings, "image_asset", "id = ?", (image_id,)) == 1
    assert (settings.data_dir / "originals" / f"{image_id}.png").is_file()


def test_purge_plan_and_apply_cover_generative_files(
    client: TestClient,
    settings: Settings,
):
    generated_dir = settings.generated_dir
    results_dir = settings.generative_results_dir
    masks_dir = settings.data_dir / "masks"
    for directory in (generated_dir, results_dir, masks_dir):
        directory.mkdir(parents=True, exist_ok=True)
    orphan_generated = generated_dir / "orphan.png"
    orphan_result = results_dir / "orphan.png"
    orphan_mask = masks_dir / "orphan.png"
    orphan_sidecar = masks_dir / "orphan.json"
    for path in (orphan_generated, orphan_result, orphan_mask, orphan_sidecar):
        path.write_bytes(b"x")

    plan = build_plan(settings)

    assert plan.orphan_generated == (orphan_generated,)
    assert plan.orphan_results == (orphan_result,)
    assert set(plan.orphan_masks) == {orphan_mask, orphan_sidecar}

    report = apply_plan(settings, plan)

    assert report.deleted_generated == 1
    assert report.deleted_results == 1
    assert report.deleted_masks == 2
    assert not any(
        path.exists() for path in (orphan_generated, orphan_result, orphan_mask, orphan_sidecar)
    )


def test_deletion_preview_counts_and_404(client: TestClient, settings: Settings):
    missing = client.get(f"/api/v1/images/{uuid4()}/deletion-preview")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "image_not_found"

    image_id, session_id = _upload_and_session(client)
    _commit(client, session_id)
    _insert_pending_analysis(settings, image_id)
    _accept_generative_edit(client, session_id)

    preview = client.get(f"/api/v1/images/{image_id}/deletion-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["imageId"] == image_id
    assert body["sessions"] == 1
    assert body["revisions"] == 3  # initial + commit + accept
    assert body["analysisTasks"] == 1
    assert body["generativeTasks"] == 1
    assert body["generativeResults"] == 1
    assert body["generatedAssets"] == 1
    assert body["generativeMasks"] == 1
