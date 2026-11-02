from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.recipe import (
    Adjustments,
    EditRecipe,
    canonical_recipe_json,
    recipe_hash,
)
from app.repositories.session_repo import (
    RevisionConflictError,
    SqliteSessionRepository,
)
from tests.conftest import make_image, upload

WORKERS = 20


def _session(client: TestClient) -> str:
    image = upload(client, make_image())
    assert image.status_code == 201
    response = client.post(
        "/api/v1/sessions",
        json={"imageId": image.json()["imageId"]},
    )
    assert response.status_code == 201
    return str(response.json()["sessionId"])


def _recipe(exposure: float) -> tuple[str, str]:
    recipe = EditRecipe(adjustments=Adjustments(exposure_ev=exposure))
    return canonical_recipe_json(recipe), recipe_hash(recipe)


def _add(
    repository: SqliteSessionRepository,
    session_id: str,
    exposure: float,
    idempotency_key: str | None,
) -> tuple[str, bool, int]:
    recipe_json, digest = _recipe(exposure)
    while True:
        session = repository.get(session_id)
        try:
            record, replayed = repository.add_revision(
                session_id,
                parent_id=session.active_revision_id,
                recipe_json=recipe_json,
                recipe_hash=digest,
                source="user",
                idempotency_key=idempotency_key,
            )
            return record.id, replayed, record.revision_no
        except RevisionConflictError:
            continue


def test_concurrent_commits_keep_revision_numbers_contiguous(
    client: TestClient,
    settings: Settings,
):
    session_id = _session(client)
    repository = SqliteSessionRepository(settings.database_path)
    exposures = [(index - 10) / 10 for index in range(WORKERS)]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda index: _add(repository, session_id, exposures[index], uuid4().hex),
                range(WORKERS),
            )
        )

    revision_numbers = sorted(number for _, _, number in results)
    assert revision_numbers == list(range(2, WORKERS + 2))
    assert len({revision_id for revision_id, _, _ in results}) == WORKERS
    assert not any(replayed for _, replayed, _ in results)

    records, next_cursor = repository.list_revisions(session_id, limit=100)
    assert next_cursor is None
    assert [record.revision_no for record in records] == list(range(WORKERS + 1, 0, -1))
    session = repository.get(session_id)
    assert session.active_revision_id == session.head_revision_id
    assert session.active_revision_id == records[0].id


def test_concurrent_retries_with_one_key_insert_exactly_once(
    client: TestClient,
    settings: Settings,
):
    session_id = _session(client)
    repository = SqliteSessionRepository(settings.database_path)
    key = uuid4().hex

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(
                lambda _: _add(repository, session_id, 0.5, key),
                range(WORKERS),
            )
        )

    assert sum(1 for _, replayed, _ in results if not replayed) == 1
    assert {number for _, _, number in results} == {2}
    assert len({revision_id for revision_id, _, _ in results}) == 1

    records, _ = repository.list_revisions(session_id, limit=100)
    assert [record.revision_no for record in records] == [2, 1]
    assert records[0].idempotency_key == key


def test_revision_paging_cursor_at_repository_boundary(
    client: TestClient,
    settings: Settings,
):
    session_id = _session(client)
    repository = SqliteSessionRepository(settings.database_path)
    for exposure in (0.1, 0.2, 0.3):
        _add(repository, session_id, exposure, uuid4().hex)

    first, cursor = repository.list_revisions(session_id, limit=2)
    second, final = repository.list_revisions(session_id, limit=2, cursor=cursor)

    assert [record.revision_no for record in first] == [4, 3]
    assert cursor == 3
    assert [record.revision_no for record in second] == [2, 1]
    assert final is None
