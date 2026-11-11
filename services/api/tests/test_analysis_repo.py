from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.contracts import AnalysisOptions
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.repositories.analysis_repo import (
    DuplicateAnalysisTaskError,
    SqliteAnalysisRepository,
)
from app.repositories.db import connect, initialize_database
from app.repositories.image_registry import ImageAssetRecord
from app.repositories.image_repo import SqliteImageRepository

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _setup(tmp_path: Path) -> tuple[Path, ImageAssetRecord, SqliteAnalysisRepository]:
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
        sha256="a" * 64,
        created_at=NOW,
    )
    SqliteImageRepository(database).add(image)
    return database, image, SqliteAnalysisRepository(database)


def _task(
    image: ImageAssetRecord,
    *,
    status: TaskStatus = TaskStatus.PENDING,
    stage: TaskStage = TaskStage.QUEUED,
    attempts: int = 0,
    dedupe_key: str | None = None,
) -> AnalysisTaskRecord:
    return AnalysisTaskRecord(
        id=str(uuid4()),
        image_id=image.id,
        image_sha256=image.sha256,
        options=AnalysisOptions(),
        config_key="config-key",
        dedupe_key=dedupe_key or uuid4().hex,
        status=status,
        stage=stage,
        attempts=attempts,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW if status is not TaskStatus.PENDING else None,
    )


def test_migration_creates_analysis_tables(tmp_path: Path):
    database, _, _ = _setup(tmp_path)

    connection = connect(database)
    try:
        names = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    finally:
        connection.close()

    assert {"analysis_task", "analysis_result"} <= names
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]


def test_create_get_and_dedupe_roundtrip(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    task = _task(image, dedupe_key="dedupe-1")

    repository.create(task)

    stored = repository.get(task.id)
    assert stored is not None
    assert stored.status is TaskStatus.PENDING
    assert stored.stage is TaskStage.QUEUED
    assert stored.options == AnalysisOptions()
    assert repository.find_by_dedupe("dedupe-1").id == task.id  # type: ignore[union-attr]

    with pytest.raises(DuplicateAnalysisTaskError, match="duplicate analysis task"):
        repository.create(_task(image, dedupe_key="dedupe-1"))


def test_latest_completed_for_image_returns_the_newest_report(tmp_path: Path):
    database, image, repository = _setup(tmp_path)
    older = _task(image, dedupe_key="older")
    newer = _task(image, dedupe_key="newer")
    repository.create(older)
    repository.create(newer)
    connection = connect(database)
    try:
        for task, completed_at in (
            (older, "2026-11-03T12:00:00Z"),
            (newer, "2026-11-03T13:00:00Z"),
        ):
            connection.execute(
                "UPDATE analysis_task SET status = ?, stage = ?, completed_at = ? WHERE id = ?",
                (TaskStatus.COMPLETED.value, TaskStage.COMPLETED.value, completed_at, task.id),
            )
            connection.execute(
                "INSERT INTO analysis_result "
                "(id, task_id, schema_version, is_mock, report_json, created_at) "
                "VALUES (?, ?, 'stage3/1', 1, '{}', ?)",
                (str(uuid4()), task.id, completed_at),
            )
    finally:
        connection.close()

    stored = repository.latest_completed_for_image(image.id)

    assert stored is not None
    assert stored.task_id == newer.id


def test_claim_is_granted_to_exactly_one_worker(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)

    winners = [repository.mark_started(task.id) for _ in range(4)]

    assert sum(winner is not None for winner in winners) == 1
    claimed = next(winner for winner in winners if winner is not None)
    assert claimed.status is TaskStatus.PROCESSING
    assert claimed.attempts == 1
    assert repository.count_queued() == 0

    # Once the row leaves processing, a worker still holding a stale claim cannot
    # write a result for it.
    assert repository.mark_failed(task.id, "vision_provider_timeout", "superseded") is True
    assert (
        repository.complete_with_result(
            task.id,
            schema_version="stage3/1",
            is_mock=True,
            report_json="{}",
        )
        is False
    )
    assert repository.get_result(task.id) is None


def test_concurrent_workers_race_for_one_claim_and_one_result_row(tmp_path: Path):
    database, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)
    workers = 8

    claim_barrier = threading.Barrier(workers)
    complete_barrier = threading.Barrier(workers)

    def claim(worker_id: int) -> bool:
        worker = SqliteAnalysisRepository(database)
        claim_barrier.wait()
        return worker.mark_started(task.id) is not None

    def complete(worker_id: int) -> bool:
        worker = SqliteAnalysisRepository(database)
        complete_barrier.wait()
        return worker.complete_with_result(
            task.id,
            schema_version="stage3/1",
            is_mock=True,
            report_json=json.dumps({"worker": worker_id}),
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        claims = list(pool.map(claim, range(workers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        completions = list(pool.map(complete, range(workers)))

    assert sum(claims) == 1
    # Exactly one result row survives and the task stays completed: the reported
    # failure mode was a losing worker turning a completed task into "failed"
    # while leaving its result row behind, making the report a permanent 409.
    assert sum(completions) == 1
    stored = repository.get(task.id)
    assert stored is not None
    assert stored.status is TaskStatus.COMPLETED
    winner = completions.index(True)
    result = repository.get_result(task.id)
    assert result is not None
    assert json.loads(result.report_json) == {"worker": winner}

    connection = connect(database)
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM analysis_result WHERE task_id = ?",
            (task.id,),
        ).fetchone()
    finally:
        connection.close()
    assert row[0] == 1


def test_count_queued_tracks_only_pending_rows(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    pending = _task(image)
    running = _task(image, status=TaskStatus.PROCESSING, stage=TaskStage.VISION, attempts=1)
    finished = _task(image)
    for task in (pending, running, finished):
        repository.create(task)
    assert repository.mark_started(finished.id) is not None
    assert repository.complete_with_result(
        finished.id,
        schema_version="stage3/1",
        is_mock=True,
        report_json="{}",
    )

    assert repository.count_queued() == 1


def test_stage_transitions_and_completion(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)

    started = repository.mark_started(task.id)
    assert started is not None
    assert started.status is TaskStatus.PROCESSING
    assert started.stage is TaskStage.PREPROCESSING
    assert started.attempts == 1
    assert started.started_at is not None

    repository.set_stage(task.id, TaskStage.VISION)
    assert repository.get(task.id).stage is TaskStage.VISION  # type: ignore[union-attr]

    repository.complete_with_result(
        task.id,
        schema_version="stage3/1",
        is_mock=True,
        report_json='{"schemaVersion":"stage3/1"}',
    )

    completed = repository.get(task.id)
    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED
    assert completed.stage is TaskStage.COMPLETED
    assert completed.completed_at is not None

    result = repository.get_result(task.id)
    assert result is not None
    assert result.schema_version == "stage3/1"
    assert result.is_mock is True
    assert result.report_json == '{"schemaVersion":"stage3/1"}'


def test_failure_and_retry_reset_clears_state(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)
    assert repository.mark_started(task.id) is not None

    assert repository.mark_failed(task.id, "vision_provider_timeout", "The provider timed out.")
    failed = repository.get(task.id)
    assert failed is not None
    assert failed.status is TaskStatus.FAILED
    assert failed.stage is TaskStage.FAILED
    assert failed.error_code == "vision_provider_timeout"

    reset = repository.reset_for_retry(task.id)
    assert reset is not None
    assert reset.status is TaskStatus.PENDING
    assert reset.stage is TaskStage.QUEUED
    assert reset.attempts == 0
    assert reset.error_code is None
    assert reset.started_at is None
    assert reset.completed_at is None
    assert repository.get_result(task.id) is None


def test_completion_locks_late_writes_out(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)
    assert repository.mark_started(task.id) is not None
    assert repository.complete_with_result(
        task.id,
        schema_version="stage3/1",
        is_mock=True,
        report_json="{}",
    )

    # A worker that lost the race must not rewrite the finished task or arm a retry.
    assert repository.mark_failed(task.id, "vision_provider_timeout", "late failure") is False
    assert repository.reset_for_retry(task.id) is None
    assert (
        repository.complete_with_result(
            task.id,
            schema_version="stage3/1",
            is_mock=True,
            report_json="{}",
        )
        is False
    )

    completed = repository.get(task.id)
    assert completed is not None
    assert completed.status is TaskStatus.COMPLETED
    assert completed.error_code is None
    assert repository.get_result(task.id) is not None


def test_reset_for_retry_clears_a_stale_result_row(tmp_path: Path):
    database, image, repository = _setup(tmp_path)
    task = _task(image)
    repository.create(task)
    assert repository.mark_started(task.id) is not None
    assert repository.complete_with_result(
        task.id,
        schema_version="stage3/1",
        is_mock=True,
        report_json="{}",
    )

    # Databases written before the status guard could leave a report attached to
    # a failed row; re-arming must not resurrect it for the next run.
    connection = connect(database)
    try:
        connection.execute(
            "UPDATE analysis_task SET status = ? WHERE id = ?",
            (TaskStatus.FAILED.value, task.id),
        )
        connection.commit()
    finally:
        connection.close()

    assert repository.reset_for_retry(task.id) is not None
    assert repository.get_result(task.id) is None


def test_delete_is_blocked_while_processing_and_cascades_result(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    processing = _task(image, status=TaskStatus.PROCESSING, stage=TaskStage.VISION)
    repository.create(processing)
    assert repository.delete_if_not_processing(processing.id) == "processing"

    assert repository.delete_if_not_processing(str(uuid4())) == "missing"

    task = _task(image)
    repository.create(task)
    repository.mark_started(task.id)
    repository.complete_with_result(
        task.id,
        schema_version="stage3/1",
        is_mock=False,
        report_json="{}",
    )
    assert repository.get_result(task.id) is not None

    assert repository.delete_if_not_processing(task.id) == "deleted"
    assert repository.get(task.id) is None
    assert repository.get_result(task.id) is None


def test_recover_startup_requeues_and_fails_over_attempt_budget(tmp_path: Path):
    _, image, repository = _setup(tmp_path)
    resumable = _task(image, status=TaskStatus.PROCESSING, stage=TaskStage.VISION, attempts=1)
    exhausted = _task(image, status=TaskStatus.PROCESSING, stage=TaskStage.DIAGNOSIS, attempts=2)
    pending = _task(image)
    completed = _task(image)
    for task in (resumable, exhausted, pending, completed):
        repository.create(task)
    assert repository.mark_started(completed.id) is not None
    assert repository.complete_with_result(
        completed.id,
        schema_version="stage3/1",
        is_mock=True,
        report_json="{}",
    )

    queued = repository.recover_startup(max_attempts=2)

    assert set(queued) == {resumable.id, pending.id}
    assert repository.get(resumable.id).status is TaskStatus.PENDING  # type: ignore[union-attr]
    assert repository.get(resumable.id).stage is TaskStage.QUEUED  # type: ignore[union-attr]
    assert repository.get(pending.id).status is TaskStatus.PENDING  # type: ignore[union-attr]

    failed = repository.get(exhausted.id)
    assert failed is not None
    assert failed.status is TaskStatus.FAILED
    assert failed.stage is TaskStage.FAILED
    assert failed.error_code == "analysis_interrupted"

    unchanged = repository.get(completed.id)
    assert unchanged is not None
    assert unchanged.status is TaskStatus.COMPLETED
