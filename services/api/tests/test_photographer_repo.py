from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.contracts import AnalysisOptions
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.models.recipe import default_recipe, recipe_hash, stored_recipe_json
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.db import connect, initialize_database
from app.repositories.image_registry import ImageAssetRecord
from app.repositories.image_repo import SqliteImageRepository
from app.repositories.photographer_repo import (
    PhotographerPlanRecord,
    SqlitePhotographerPlanRepository,
)
from app.repositories.session_repo import SqliteSessionRepository

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _setup(
    tmp_path: Path,
) -> tuple[Path, SqlitePhotographerPlanRepository, str, str, str]:
    database = tmp_path / "frame.db"
    initialize_database(database)
    image = ImageAssetRecord(
        id=str(uuid4()),
        original_name="photo.png",
        storage_key=f"originals/{uuid4()}.png",
        mime_type="image/png",
        width=64,
        height=48,
        exif_orientation=1,
        bytes=128,
        sha256="b" * 64,
        created_at=NOW,
    )
    SqliteImageRepository(database).add(image)
    recipe = default_recipe()
    session, _ = SqliteSessionRepository(database).create_session(
        image.id,
        recipe_json=stored_recipe_json(recipe),
        recipe_hash=recipe_hash(recipe),
    )
    task = AnalysisTaskRecord(
        id=str(uuid4()),
        image_id=image.id,
        image_sha256=image.sha256,
        options=AnalysisOptions(),
        config_key="config-key",
        dedupe_key=uuid4().hex,
        status=TaskStatus.COMPLETED,
        stage=TaskStage.COMPLETED,
        attempts=1,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        completed_at=NOW,
    )
    SqliteAnalysisRepository(database).create(task)
    return database, SqlitePhotographerPlanRepository(database), image.id, session.id, task.id


def _record(
    image_id: str,
    session_id: str,
    analysis_id: str,
    *,
    created_at: datetime = NOW,
    mode: str = "auto",
    is_mock: bool = True,
    degraded: bool = False,
) -> PhotographerPlanRecord:
    recipe = default_recipe()
    return PhotographerPlanRecord(
        id=str(uuid4()),
        image_id=image_id,
        session_id=session_id,
        analysis_id=analysis_id,
        mode=mode,
        style_id=None,
        style_version=None,
        style_strength=None,
        provider="mock",
        model="mock-planner",
        prompt_version="stage5-planner/1",
        is_mock=is_mock,
        degraded=degraded,
        confidence=0.7,
        plan_json='{"planId":"stub"}',
        recipe_json=stored_recipe_json(recipe),
        recipe_hash=recipe_hash(recipe),
        created_at=created_at,
    )


def test_create_get_and_query_latest_plan(tmp_path: Path):
    _, repository, image_id, session_id, analysis_id = _setup(tmp_path)
    first = _record(image_id, session_id, analysis_id, created_at=NOW)
    second = _record(
        image_id,
        session_id,
        analysis_id,
        created_at=NOW + timedelta(seconds=1),
        degraded=True,
    )

    repository.create(first)
    repository.create(second)

    stored = repository.get(first.id)
    assert stored is not None
    assert stored.is_mock is True
    assert stored.degraded is False
    assert stored.confidence == 0.7

    latest = repository.latest_for_session(session_id)
    assert latest is not None
    assert latest.id == second.id
    assert latest.degraded is True
    assert repository.latest_for_image(image_id).id == second.id  # type: ignore[union-attr]

    listed = repository.list_for_session(session_id, limit=1)
    assert [item.id for item in listed] == [second.id]
    assert repository.get(str(uuid4())) is None


def test_plan_is_removed_with_its_session(tmp_path: Path):
    database, repository, image_id, session_id, analysis_id = _setup(tmp_path)
    plan = _record(image_id, session_id, analysis_id)
    repository.create(plan)

    connection = connect(database)
    try:
        connection.execute("DELETE FROM edit_session WHERE id = ?", (session_id,))
        remaining = connection.execute(
            "SELECT COUNT(*) AS total FROM photographer_plan WHERE id = ?",
            (plan.id,),
        ).fetchone()
    finally:
        connection.close()

    assert remaining is not None
    assert int(remaining["total"]) == 0


def test_plan_mode_is_constrained(tmp_path: Path):
    _, repository, image_id, session_id, analysis_id = _setup(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        repository.create(_record(image_id, session_id, analysis_id, mode="invalid"))
