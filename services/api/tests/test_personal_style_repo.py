from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleConsentScope,
    PersonalStyleDefinition,
    PersonalStyleProfile,
    PersonalStyleReference,
    PersonalStyleReferenceStatus,
    PersonalStyleSource,
    PersonalStyleStatus,
    build_default_personal_profile,
)
from app.repositories.db import connect, initialize_database
from app.repositories.deletion_repo import SqliteDeletionRepository
from app.repositories.personal_style_repo import (
    DuplicatePersonalStyleIdError,
    DuplicatePersonalStyleNameError,
    PersonalStyleNotFoundError,
    PersonalStyleVersionConflictError,
    SqlitePersonalStyleRepository,
)

OWNER = "local"
OTHER_OWNER = "someone-else"
STYLE_ID = "personal_abcdef123456"


def _profile(
    *,
    style_id: str = STYLE_ID,
    name: str = "克制的城市",
    source: PersonalStyleSource = PersonalStyleSource.PHOTOS,
    targets: dict[str, float] | None = None,
) -> PersonalStyleProfile:
    return build_default_personal_profile(
        style_id=style_id,
        name=name,
        description="低饱和的街头叙事。",
        source=source,
        targets=targets,
    )


def _definition() -> PersonalStyleDefinition:
    return PersonalStyleDefinition()


def _insert_image(path: Path, image_id: UUID, sha256: str) -> None:
    connection = connect(path)
    try:
        connection.execute(
            "INSERT INTO image_asset "
            "(id, original_name, storage_key, mime_type, width, height, "
            " exif_orientation, bytes, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(image_id),
                "street.png",
                f"originals/{image_id}.png",
                "image/png",
                96,
                64,
                1,
                128,
                sha256,
                "2026-11-09T00:00:00Z",
            ),
        )
    finally:
        connection.close()


def _reference(image_id: UUID, sha256: str) -> PersonalStyleReference:
    now = datetime.now(UTC)
    return PersonalStyleReference(
        id=uuid4(),
        image_id=image_id,
        image_sha256=sha256,
        original_name="street.png",
        status=PersonalStyleReferenceStatus.ACTIVE,
        consent_scope=PersonalStyleConsentScope.ANALYSIS_ONLY,
        consent_at=now,
        added_at=now,
    )


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "frame.db"
    initialize_database(path)
    return path


@pytest.fixture
def repo(database: Path) -> SqlitePersonalStyleRepository:
    return SqlitePersonalStyleRepository(database)


def test_migration_creates_personal_style_tables(database: Path) -> None:
    connection = connect(database)
    try:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        versions = [
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        issues = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()

    assert {
        "personal_style",
        "personal_style_version",
        "personal_style_reference",
        "personal_style_photo_feature",
        "personal_style_feedback",
        "personal_style_evolution",
        "personal_style_tombstone",
    } <= tables
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert issues == []


def test_the_public_archive_still_rejects_personal_kind(database: Path) -> None:
    connection = connect(database)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO style_profile "
                "(id, kind, name, current_version, enabled, created_at, updated_at) "
                "VALUES ('personal_abcdef123456', 'personal', '私有风格', '1.0', 0, "
                "'2026-11-09T00:00:00Z', '2026-11-09T00:00:00Z')"
            )
    finally:
        connection.close()


def test_create_get_and_owner_isolation(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)

    record = repo.get(STYLE_ID, owner_id=OWNER)
    assert record is not None
    assert record.head.status is PersonalStyleStatus.DRAFT
    assert record.head.favorite is False
    assert record.profile.kind.value == "personal"
    assert record.profile.personal.source is PersonalStyleSource.PHOTOS
    assert record.profile.enabled is False
    assert repo.get(STYLE_ID, owner_id=OTHER_OWNER) is None
    assert repo.list_records(owner_id=OTHER_OWNER) == []
    assert len(repo.list_records(owner_id=OWNER)) == 1


def test_duplicate_id_and_name_are_rejected(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)

    with pytest.raises(DuplicatePersonalStyleIdError):
        repo.create(_profile(name="另一个名字"), _definition(), owner_id=OWNER)
    with pytest.raises(DuplicatePersonalStyleNameError):
        repo.create(
            _profile(style_id="personal_ffffffffffff"),
            _definition(),
            owner_id=OWNER,
        )
    assert len(repo.list_records(owner_id=OWNER)) == 1


def test_versions_are_immutable_and_monotonic(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)
    revised = _profile(name="克制的城市 II", targets={"saturation": -12.0}).model_copy(
        update={"version": "1.1"}
    )
    repo.add_version(
        revised,
        _definition(),
        owner_id=OWNER,
        change_source=PersonalStyleChangeSource.USER,
    )

    current = repo.get(STYLE_ID, owner_id=OWNER)
    assert current is not None
    assert current.profile.version == "1.1"
    assert current.head.name == "克制的城市 II"
    assert current.profile.personal.targets["saturation"] == -12.0
    old = repo.get(STYLE_ID, owner_id=OWNER, version="1.0")
    assert old is not None
    assert old.profile.name == "克制的城市"
    assert old.profile.version == "1.0"
    assert old.profile.personal.targets == {}
    assert [item.version for item in repo.list_versions(STYLE_ID, owner_id=OWNER)] == [
        "1.1",
        "1.0",
    ]

    with pytest.raises(PersonalStyleVersionConflictError):
        repo.add_version(
            revised,
            _definition(),
            owner_id=OWNER,
            change_source=PersonalStyleChangeSource.USER,
        )
    with pytest.raises(PersonalStyleVersionConflictError):
        repo.add_version(
            _profile(name="改回旧版", source=PersonalStyleSource.CUSTOM).model_copy(
                update={"version": "1.2"}
            ),
            _definition(),
            owner_id=OWNER,
            change_source=PersonalStyleChangeSource.USER,
        )


def test_add_version_rejects_a_duplicate_name(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)
    other_id = "personal_ffffffffffff"
    repo.create(_profile(style_id=other_id, name="另一个风格"), _definition(), owner_id=OWNER)
    revised = _profile(name="另一个风格").model_copy(update={"version": "1.1"})
    with pytest.raises(DuplicatePersonalStyleNameError):
        repo.add_version(
            revised,
            _definition(),
            owner_id=OWNER,
            change_source=PersonalStyleChangeSource.USER,
        )


def test_add_version_requires_the_same_owner(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)
    revised = _profile().model_copy(update={"version": "1.1"})
    with pytest.raises(PersonalStyleNotFoundError):
        repo.add_version(
            revised,
            _definition(),
            owner_id=OTHER_OWNER,
            change_source=PersonalStyleChangeSource.USER,
        )


def test_status_and_favorite_are_head_state(repo: SqlitePersonalStyleRepository) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)
    repo.set_status(STYLE_ID, owner_id=OWNER, status=PersonalStyleStatus.PUBLISHED)
    repo.set_favorite(STYLE_ID, owner_id=OWNER, favorite=True)

    record = repo.get(STYLE_ID, owner_id=OWNER)
    assert record is not None
    assert record.head.status is PersonalStyleStatus.PUBLISHED
    assert record.head.favorite is True
    assert record.profile.enabled is True
    archived = repo.get(STYLE_ID, owner_id=OWNER, version="1.0")
    assert archived is not None
    assert archived.profile.enabled is True

    repo.set_status(STYLE_ID, owner_id=OWNER, status=PersonalStyleStatus.DISABLED)
    record = repo.get(STYLE_ID, owner_id=OWNER)
    assert record is not None
    assert record.profile.enabled is False
    with pytest.raises(PersonalStyleNotFoundError):
        repo.set_status(STYLE_ID, owner_id=OTHER_OWNER, status=PersonalStyleStatus.DISABLED)


def test_references_are_idempotent_and_removable(
    repo: SqlitePersonalStyleRepository,
    database: Path,
) -> None:
    image_id = uuid4()
    sha = "a" * 64
    _insert_image(database, image_id, sha)
    repo.create(_profile(), _definition(), owner_id=OWNER)

    added = repo.add_references(
        STYLE_ID,
        owner_id=OWNER,
        references=[_reference(image_id, sha)],
    )
    assert len(added) == 1
    assert added[0].image_id == image_id
    again = repo.add_references(
        STYLE_ID,
        owner_id=OWNER,
        references=[_reference(image_id, sha)],
    )
    assert len(again) == 1
    listed = repo.list_records(owner_id=OWNER)
    assert listed[0].reference_count == 1

    reference_id = str(added[0].id)
    assert repo.remove_reference(STYLE_ID, reference_id, owner_id=OWNER) is True
    assert repo.remove_reference(STYLE_ID, reference_id, owner_id=OWNER) is False
    assert repo.list_references(STYLE_ID, owner_id=OWNER) == []


def test_delete_removes_aggregate_and_keeps_a_tombstone(
    repo: SqlitePersonalStyleRepository,
    database: Path,
) -> None:
    repo.create(_profile(), _definition(), owner_id=OWNER)
    assert repo.delete(STYLE_ID, owner_id=OTHER_OWNER) == "missing"
    assert repo.delete(STYLE_ID, owner_id=OWNER) == "deleted"
    assert repo.get(STYLE_ID, owner_id=OWNER) is None
    assert repo.list_versions(STYLE_ID, owner_id=OWNER) == []
    assert repo.delete(STYLE_ID, owner_id=OWNER) == "tombstoned"

    connection = connect(database)
    try:
        versions = connection.execute(
            "SELECT COUNT(*) FROM personal_style_version WHERE style_id = ?",
            (STYLE_ID,),
        ).fetchone()[0]
        tombstone = connection.execute(
            "SELECT COUNT(*) FROM personal_style_tombstone WHERE style_id = ?",
            (STYLE_ID,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert versions == 0
    assert tombstone == 1


def test_deleting_an_image_detaches_references_but_keeps_the_style(
    repo: SqlitePersonalStyleRepository,
    database: Path,
) -> None:
    image_id = uuid4()
    sha = "b" * 64
    _insert_image(database, image_id, sha)
    repo.create(_profile(), _definition(), owner_id=OWNER)
    references = repo.add_references(
        STYLE_ID,
        owner_id=OWNER,
        references=[_reference(image_id, sha)],
    )
    reference_id = str(references[0].id)

    connection = connect(database)
    try:
        connection.execute(
            "INSERT INTO personal_style_photo_feature "
            "(reference_id, style_id, image_sha256, analysis_id, extractor_version, "
            " features_json, confidence, is_mock, created_at) "
            "VALUES (?, ?, ?, ?, ?, '{}', 0.8, 1, ?)",
            (reference_id, STYLE_ID, sha, str(uuid4()), "visual-dna/1", "2026-11-09T00:00:00Z"),
        )
    finally:
        connection.close()

    assert SqliteDeletionRepository(database).delete_image(str(image_id)).status == "deleted"

    record = repo.get(STYLE_ID, owner_id=OWNER)
    assert record is not None
    references = repo.list_references(STYLE_ID, owner_id=OWNER)
    assert len(references) == 1
    assert references[0].image_id is None
    assert references[0].status is PersonalStyleReferenceStatus.MISSING

    connection = connect(database)
    try:
        features = connection.execute(
            "SELECT COUNT(*) FROM personal_style_photo_feature WHERE reference_id = ?",
            (reference_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert features == 0
