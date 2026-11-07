from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.contracts import AnalysisOptions
from app.models.analysis_task import AnalysisTaskRecord, TaskStage, TaskStatus
from app.models.photographer import (
    FeedbackAction,
    FeedbackRubric,
    FeedbackSource,
    FeedbackSummary,
)
from app.models.recipe import (
    Adjustments,
    Crop,
    CurvePoint,
    CurveSet,
    EditRecipe,
    HslAdjustments,
    HslBand,
    LocalAdjustment,
    LocalAdjustments,
    OutputSettings,
    UserMask,
    recipe_hash,
    stored_recipe_json,
)
from app.photographer.feedback import (
    changed_paths,
    derive_action,
    flatten_recipe,
    rubric_values,
    summarize,
)
from app.repositories.analysis_repo import SqliteAnalysisRepository
from app.repositories.db import connect, initialize_database
from app.repositories.image_registry import ImageAssetRecord
from app.repositories.image_repo import SqliteImageRepository
from app.repositories.photographer_repo import (
    PhotographerFeedbackRecord,
    PhotographerPlanRecord,
    SqlitePhotographerFeedbackRepository,
    SqlitePhotographerPlanRepository,
)
from app.repositories.session_repo import SqliteSessionRepository

_NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> PhotographerFeedbackRecord:
    fields: dict[str, object] = {
        "id": str(uuid4()),
        "image_id": str(uuid4()),
        "session_id": str(uuid4()),
        "plan_id": None,
        "revision_id": None,
        "source": FeedbackSource.PLAN.value,
        "action": FeedbackAction.ACCEPTED.value,
        "changed_paths": (),
        "rubric": None,
        "is_mock": True,
        "degraded": False,
        "created_at": _NOW,
    }
    fields.update(overrides)
    return PhotographerFeedbackRecord(**fields)  # type: ignore[arg-type]


def _adjustments(**overrides: float) -> EditRecipe:
    return EditRecipe(adjustments=Adjustments.model_validate(overrides))


@dataclass(frozen=True, slots=True)
class _Scaffold:
    """The rows a feedback row's foreign keys are allowed to point at."""

    store: SqlitePhotographerFeedbackRepository
    image_id: str
    session_id: str
    revision_id: str
    next_revision_id: str
    plan_id: str


def _seed_scaffold(database_path: Path) -> _Scaffold:
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
        created_at=_NOW,
    )
    SqliteImageRepository(database_path).add(image)

    session_repo = SqliteSessionRepository(database_path)
    recipe = EditRecipe()
    recipe_json = stored_recipe_json(recipe)
    digest = recipe_hash(recipe)
    session, revision = session_repo.create_session(
        image.id,
        recipe_json=recipe_json,
        recipe_hash=digest,
    )
    next_revision, _ = session_repo.add_revision(
        session.id,
        parent_id=revision.id,
        recipe_json=recipe_json,
        recipe_hash=digest,
        source="user",
        idempotency_key=None,
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
        created_at=_NOW,
        updated_at=_NOW,
        started_at=_NOW,
        completed_at=_NOW,
    )
    SqliteAnalysisRepository(database_path).create(task)

    plan = PhotographerPlanRecord(
        id=str(uuid4()),
        image_id=image.id,
        session_id=session.id,
        analysis_id=task.id,
        mode="auto",
        style_id=None,
        style_version=None,
        style_strength=None,
        provider="mock",
        model="mock-planner",
        prompt_version="stage5-planner/1",
        is_mock=True,
        degraded=False,
        confidence=0.7,
        plan_json='{"planId":"stub"}',
        recipe_json=recipe_json,
        recipe_hash=digest,
        created_at=_NOW,
    )
    SqlitePhotographerPlanRepository(database_path).create(plan)

    return _Scaffold(
        store=SqlitePhotographerFeedbackRepository(database_path),
        image_id=image.id,
        session_id=session.id,
        revision_id=revision.id,
        next_revision_id=next_revision.id,
        plan_id=plan.id,
    )


def _stored(scaffold: _Scaffold, **overrides: object) -> PhotographerFeedbackRecord:
    """A record whose image, session and revision ids really exist."""
    fields: dict[str, object] = {
        "image_id": scaffold.image_id,
        "session_id": scaffold.session_id,
        "revision_id": scaffold.revision_id,
    }
    fields.update(overrides)
    return _record(**fields)  # type: ignore[arg-type]


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "feedback.sqlite3"
    initialize_database(path)
    return path


@pytest.fixture
def scaffold(database_path: Path) -> _Scaffold:
    return _seed_scaffold(database_path)


def test_identical_recipes_move_nothing() -> None:
    assert changed_paths(EditRecipe(), EditRecipe()) == ()


def test_a_slider_move_is_reported_by_its_own_path() -> None:
    assert changed_paths(EditRecipe(), _adjustments(exposureEv=0.7)) == ("adjustments.exposureEv",)
    moved = changed_paths(_adjustments(contrast=12.0), _adjustments(temperature=-8.0))
    assert moved == ("adjustments.contrast", "adjustments.temperature")


def test_reverting_a_parameter_counts_as_a_change() -> None:
    assert changed_paths(_adjustments(shadows=25.0), EditRecipe()) == ("adjustments.shadows",)


def test_curve_and_mask_state_are_named_as_one_block_each() -> None:
    curves = EditRecipe(
        curve=CurveSet(master=(CurvePoint(x=0.25, y=0.4), CurvePoint(x=0.75, y=0.8)))
    )
    assert changed_paths(EditRecipe(), curves) == ("curve.master",)

    masked = EditRecipe(masks=(UserMask(id="mask_001", x=0.0, y=0.0, width=0.5, height=0.5),))
    assert changed_paths(EditRecipe(), masked) == ("masks",)


def test_local_adjustments_are_reported_without_inventing_mask_paths() -> None:
    local = EditRecipe(
        local_adjustments=(
            LocalAdjustment(
                id="local_001",
                mask_id="mask_001",
                adjustments=LocalAdjustments(exposure_ev=0.5),
            ),
        )
    )
    assert changed_paths(EditRecipe(), local) == ("localAdjustments",)


def test_a_crop_is_named_by_its_corner_values() -> None:
    cropped = EditRecipe(adjustments=Adjustments(crop=Crop(x=0.1, y=0.2, w=0.7, h=0.6)))
    assert changed_paths(EditRecipe(), cropped) == (
        "adjustments.crop.h",
        "adjustments.crop.w",
        "adjustments.crop.x",
        "adjustments.crop.y",
    )


def test_hsl_channels_are_named_by_hue_saturation_and_luminance() -> None:
    hsl = EditRecipe(hsl=HslAdjustments(red=HslBand(hue=6.0)))
    assert changed_paths(EditRecipe(), hsl) == ("hsl.red.hue",)


def test_prose_and_export_settings_are_not_parameter_changes() -> None:
    annotated = EditRecipe(rationale=["提高阴影"], warnings=["注意噪点"])
    assert changed_paths(EditRecipe(), annotated) == ()

    exported = EditRecipe(output=OutputSettings(quality=70))
    assert changed_paths(EditRecipe(), exported) == ()


def test_flatten_recipe_uses_the_wire_names() -> None:
    leaves = flatten_recipe(_adjustments(exposureEv=0.7, rotationDeg=1.5))
    assert leaves["adjustments.exposureEv"] == 0.7
    assert leaves["adjustments.rotationDeg"] == 1.5
    assert "schemaVersion" not in leaves
    assert leaves["adjustments.crop"] is None


def test_a_missing_baseline_reports_every_stored_leaf() -> None:
    paths = changed_paths(None, _adjustments(vignette=-12.0))
    assert "adjustments.vignette" in paths
    assert "adjustments.exposureEv" in paths


def test_matching_recipe_stays_accepted_and_any_drift_becomes_modified() -> None:
    plan = _adjustments(highlights=-20.0)
    assert (
        derive_action(action=FeedbackAction.ACCEPTED, plan_recipe=plan, revision_recipe=plan)
        is FeedbackAction.ACCEPTED
    )
    assert (
        derive_action(
            action=FeedbackAction.ACCEPTED,
            plan_recipe=plan,
            revision_recipe=_adjustments(highlights=-20.0, contrast=8.0),
        )
        is FeedbackAction.MODIFIED
    )


def test_unrelated_actions_and_missing_anchors_pass_through() -> None:
    plan = _adjustments()
    for action in (FeedbackAction.REJECTED, FeedbackAction.RESET, FeedbackAction.MODIFIED):
        assert derive_action(action=action, plan_recipe=plan, revision_recipe=plan) is action
    assert (
        derive_action(action=FeedbackAction.ACCEPTED, plan_recipe=None, revision_recipe=plan)
        is FeedbackAction.ACCEPTED
    )
    assert (
        derive_action(action=FeedbackAction.ACCEPTED, plan_recipe=plan, revision_recipe=None)
        is FeedbackAction.ACCEPTED
    )


def test_only_the_scored_dimensions_are_stored() -> None:
    assert rubric_values(None) is None
    assert rubric_values(FeedbackRubric()) is None
    assert rubric_values(FeedbackRubric(exposure=4, skin_tone=2)) == {"exposure": 4, "skin_tone": 2}


def test_summary_counts_behaviours_without_judging_quality() -> None:
    records = [
        _record(action="accepted", source="plan", is_mock=True),
        _record(action="accepted", source="chat", is_mock=False),
        _record(
            action="modified", source="chat", changed_paths=("adjustments.contrast",), is_mock=False
        ),
        _record(action="rejected", source="critique", degraded=True),
        _record(action="reset", source=None, rubric={"exposure": 3}, is_mock=False),
    ]
    summary = summarize(records)

    assert (summary.total, summary.accepted, summary.rejected) == (5, 2, 1)
    assert (summary.modified, summary.reset) == (1, 1)
    assert (summary.by_source.plan, summary.by_source.chat) == (1, 2)
    assert (summary.by_source.critique, summary.by_source.unset) == (1, 1)
    assert (summary.mock_count, summary.real_count) == (2, 3)
    assert (summary.degraded_count, summary.rated_count) == (1, 1)
    assert summary.change_frequency[0].path == "adjustments.contrast"
    assert summary.change_frequency[0].count == 1
    assert [(row.dimension.value, row.average, row.count) for row in summary.rubric_averages] == [
        ("exposure", 3.0, 1)
    ]


def test_summary_of_nothing_is_honest_about_being_empty() -> None:
    summary = summarize(())
    assert isinstance(summary, FeedbackSummary)
    assert summary.total == 0
    assert summary.accepted == summary.rejected == summary.modified == summary.reset == 0
    assert summary.change_frequency == ()
    assert summary.rubric_averages == ()
    assert summary.disclaimers


def test_the_summary_exposes_behaviour_and_scores_but_no_quality_verdict() -> None:
    fields = set(FeedbackSummary.model_fields)
    for forbidden in {
        "improved",
        "improvement",
        "quality_gain",
        "better",
        "success_rate",
        "average_score",
    }:
        assert forbidden not in fields

    wording = "".join(summarize(()).disclaimers)
    assert wording
    for forbidden in ("质量提升", "变得更好", "improved", "better"):
        assert forbidden not in wording


def test_rubric_averages_only_cover_dimensions_that_were_scored() -> None:
    records = [
        _record(rubric={"exposure": 5, "color": 4}),
        _record(rubric={"exposure": 3}),
        _record(rubric={"style": 1}),
    ]
    averages = {
        row.dimension.value: (row.average, row.count) for row in summarize(records).rubric_averages
    }
    assert averages == {"exposure": (4.0, 2), "color": (4.0, 1), "style": (1.0, 1)}


def test_change_frequency_ranks_the_most_moved_parameters_first() -> None:
    records = [
        _record(changed_paths=("adjustments.contrast", "adjustments.shadows")),
        _record(changed_paths=("adjustments.contrast",)),
        _record(changed_paths=("hsl.red.hue", "adjustments.contrast")),
    ]
    ranked = [(row.path, row.count) for row in summarize(records).change_frequency]
    assert ranked[0] == ("adjustments.contrast", 3)
    assert {path for path, _ in ranked} == {
        "adjustments.contrast",
        "adjustments.shadows",
        "hsl.red.hue",
    }


def test_a_record_round_trips_through_sqlite(scaffold: _Scaffold) -> None:
    record = _stored(
        scaffold,
        changed_paths=("adjustments.contrast", "curve.master"),
        rubric={"exposure": 4, "naturalness": 3},
        degraded=True,
        is_mock=False,
    )
    scaffold.store.record(record)

    stored = scaffold.store.get(record.id)
    assert stored is not None
    assert stored == record
    assert stored.created_at == _NOW


def test_the_latest_row_for_one_plan_and_action_replaces_the_previous_one(
    scaffold: _Scaffold,
) -> None:
    first = _stored(
        scaffold,
        plan_id=scaffold.plan_id,
        action="accepted",
        created_at=datetime(2026, 11, 5, 12, 0, tzinfo=UTC),
    )
    stale = _stored(
        scaffold,
        plan_id=scaffold.plan_id,
        action="accepted",
        revision_id=scaffold.next_revision_id,
        changed_paths=("adjustments.shadows",),
        created_at=datetime(2026, 11, 5, 9, 0, tzinfo=UTC),
    )
    scaffold.store.record(first)
    scaffold.store.record(stale)

    stored = scaffold.store.get(first.id)
    assert stored is not None
    assert stored.revision_id == stale.revision_id
    assert stored.changed_paths == ("adjustments.shadows",)
    assert stored.created_at == first.created_at, "the original event keeps its timestamp"
    assert len(scaffold.store.list_recent(plan_id=scaffold.plan_id)) == 1


def test_records_without_a_plan_are_kept_apart(scaffold: _Scaffold) -> None:
    first, second = _stored(scaffold, action="reset"), _stored(scaffold, action="reset")
    scaffold.store.record(first)
    scaffold.store.record(second)

    stored = scaffold.store.list_recent()
    assert {record.id for record in stored} == {first.id, second.id}
    assert {record.action for record in stored} == {"reset"}


def test_listing_filters_by_session_image_and_plan(
    scaffold: _Scaffold,
    database_path: Path,
) -> None:
    other = _seed_scaffold(database_path)
    mine = _stored(scaffold, plan_id=scaffold.plan_id)
    theirs = _stored(other, created_at=datetime(2026, 11, 5, 11, 0, tzinfo=UTC))
    older = _stored(scaffold, created_at=datetime(2026, 11, 5, 8, 0, tzinfo=UTC))
    for record in (theirs, older, mine):
        scaffold.store.record(record)

    assert [record.id for record in scaffold.store.list_recent(session_id=scaffold.session_id)] == [
        mine.id,
        older.id,
    ]
    assert [record.id for record in scaffold.store.list_recent(image_id=scaffold.image_id)] == [
        mine.id,
        older.id,
    ]
    assert [record.id for record in scaffold.store.list_recent(plan_id=scaffold.plan_id)] == [
        mine.id
    ]
    assert [record.id for record in scaffold.store.list_recent(limit=2)] == [mine.id, theirs.id]
    assert [record.id for record in scaffold.store.list_recent()] == [mine.id, theirs.id, older.id]


def test_deleting_reports_whether_the_row_existed(scaffold: _Scaffold) -> None:
    record = _stored(scaffold)
    scaffold.store.record(record)

    assert scaffold.store.delete(record.id) is True
    assert scaffold.store.get(record.id) is None
    assert scaffold.store.delete(record.id) is False


def test_feedback_disappears_with_the_session_then_the_image(
    scaffold: _Scaffold,
    database_path: Path,
) -> None:
    record = _stored(scaffold)
    scaffold.store.record(record)

    connection = connect(database_path)
    try:
        connection.execute("DELETE FROM edit_session WHERE id = ?", (scaffold.session_id,))
        assert scaffold.store.get(record.id) is None, (
            "session deletion must take the feedback with it"
        )

        connection.execute("DELETE FROM image_asset WHERE id = ?", (scaffold.image_id,))
    finally:
        connection.close()

    survivor = _stored(_seed_scaffold(database_path))
    scaffold.store.record(survivor)
    assert scaffold.store.get(survivor.id) == survivor


def test_sqlite_rejects_actions_and_sources_outside_the_vocabulary(scaffold: _Scaffold) -> None:
    for action in ("improved", ""):
        with pytest.raises(sqlite3.IntegrityError):
            scaffold.store.record(_stored(scaffold, action=action))
    for source in ("email", "auto"):
        with pytest.raises(sqlite3.IntegrityError):
            scaffold.store.record(_stored(scaffold, source=source))
