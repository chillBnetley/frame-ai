from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.models.personal_style import (
    PersonalStyleChangeSource,
    PersonalStyleDefinition,
    PersonalStyleProfile,
    PersonalStyleReference,
    PersonalStyleSource,
    PersonalStyleStatus,
)
from app.models.visual_dna import PhotoVisualFeatures
from app.repositories.db import connect, utc_now


class PersonalStyleNotFoundError(LookupError):
    """The requested personal style does not exist for this owner."""


class DuplicatePersonalStyleIdError(ValueError):
    """A personal style with the same identifier already exists."""


class DuplicatePersonalStyleNameError(ValueError):
    """This owner already has a personal style with the same name."""


class PersonalStyleVersionConflictError(ValueError):
    """The version is not strictly newer, or immutable fields changed."""


class PersonalStyleReferenceNotFoundError(LookupError):
    """The requested reference photo does not belong to this personal style."""


class PersonalStyleFeatureMismatchError(ValueError):
    """The extracted features do not belong to the reference photo."""


@dataclass(frozen=True, slots=True)
class PersonalStyleHead:
    id: str
    owner_id: str
    name: str
    description: str
    source: PersonalStyleSource
    status: PersonalStyleStatus
    favorite: bool
    current_version: str
    created_at: datetime
    updated_at: datetime
    deleted_at: str | None = None


@dataclass(frozen=True, slots=True)
class PersonalStyleRecord:
    head: PersonalStyleHead
    profile: PersonalStyleProfile
    definition: PersonalStyleDefinition


@dataclass(frozen=True, slots=True)
class PersonalStyleListItemRecord:
    head: PersonalStyleHead
    profile: PersonalStyleProfile
    reference_count: int


@dataclass(frozen=True, slots=True)
class PersonalStyleVersionRecord:
    version: str
    change_source: PersonalStyleChangeSource
    change_note: str | None
    created_at: datetime


DeletionStatus = Literal["deleted", "tombstoned", "missing"]


def _version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def _parse_time(value: object) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _head_from_row(row: sqlite3.Row) -> PersonalStyleHead:
    return PersonalStyleHead(
        id=str(row["id"]),
        owner_id=str(row["owner_id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        source=PersonalStyleSource(str(row["source"])),
        status=PersonalStyleStatus(str(row["status"])),
        favorite=bool(row["favorite"]),
        current_version=str(row["current_version"]),
        created_at=_parse_time(row["created_at"]),
        updated_at=_parse_time(row["updated_at"]),
        deleted_at=None if row["deleted_at"] is None else str(row["deleted_at"]),
    )


def _profile_from_row(row: sqlite3.Row, *, status: PersonalStyleStatus) -> PersonalStyleProfile:
    profile = PersonalStyleProfile.model_validate_json(str(row["profile_json"]))
    # Publication state is head state, not version content: overlaying it keeps
    # archive snapshots immutable while disabling draft/disabled profiles.
    enabled = status is PersonalStyleStatus.PUBLISHED
    if profile.enabled != enabled:
        profile = profile.model_copy(update={"enabled": enabled})
    return profile


def _record_from_rows(
    head_row: sqlite3.Row,
    version_row: sqlite3.Row,
) -> PersonalStyleRecord:
    head = _head_from_row(head_row)
    return PersonalStyleRecord(
        head=head,
        profile=_profile_from_row(version_row, status=head.status),
        definition=PersonalStyleDefinition.model_validate_json(str(version_row["definition_json"])),
    )


def _reference_from_row(row: sqlite3.Row) -> PersonalStyleReference:
    return PersonalStyleReference.model_validate(
        {
            "id": row["id"],
            "image_id": row["image_id"],
            "image_sha256": row["image_sha256"],
            "original_name": row["original_name"],
            "status": row["status"],
            "consent_scope": row["consent_scope"],
            "consent_at": _parse_time(row["consent_at"]),
            "added_at": _parse_time(row["added_at"]),
            "analysis_id": row["analysis_id"],
        }
    )


class SqlitePersonalStyleRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def create(
        self,
        profile: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        *,
        owner_id: str,
        status: PersonalStyleStatus = PersonalStyleStatus.DRAFT,
        change_source: PersonalStyleChangeSource = PersonalStyleChangeSource.CUSTOM,
        change_note: str | None = None,
    ) -> None:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO personal_style "
                "(id, owner_id, name, description, source, status, favorite, "
                " current_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    profile.id,
                    owner_id,
                    profile.name,
                    profile.description,
                    profile.personal.source.value,
                    status.value,
                    profile.version,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO personal_style_version "
                "(style_id, version, profile_json, definition_json, change_source, "
                " change_note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.id,
                    profile.version,
                    profile.model_dump_json(by_alias=True),
                    definition.model_dump_json(by_alias=True),
                    change_source.value,
                    change_note,
                    now,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            message = str(exc)
            if "personal_style.id" in message:
                raise DuplicatePersonalStyleIdError(
                    f"personal style '{profile.id}' already exists"
                ) from exc
            raise DuplicatePersonalStyleNameError(
                f"owner '{owner_id}' already has a personal style named '{profile.name}'"
            ) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(
        self,
        style_id: str,
        *,
        owner_id: str,
        version: str | None = None,
    ) -> PersonalStyleRecord | None:
        connection = connect(self._path)
        try:
            head_row = connection.execute(
                "SELECT * FROM personal_style WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                (style_id, owner_id),
            ).fetchone()
            if head_row is None:
                return None
            if version is None:
                version_row = connection.execute(
                    "SELECT * FROM personal_style_version WHERE style_id = ? AND version = ?",
                    (style_id, str(head_row["current_version"])),
                ).fetchone()
            else:
                version_row = connection.execute(
                    "SELECT * FROM personal_style_version WHERE style_id = ? AND version = ?",
                    (style_id, version),
                ).fetchone()
            if version_row is None:
                return None
            return _record_from_rows(head_row, version_row)
        finally:
            connection.close()

    def list_records(
        self,
        *,
        owner_id: str,
        status: PersonalStyleStatus | None = None,
    ) -> list[PersonalStyleListItemRecord]:
        clauses = ["p.owner_id = ?", "p.deleted_at IS NULL"]
        params: list[object] = [owner_id]
        if status is not None:
            clauses.append("p.status = ?")
            params.append(status.value)
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT p.*, v.profile_json AS profile_json, "
                "(SELECT COUNT(*) FROM personal_style_reference r "
                " WHERE r.style_id = p.id AND r.status = 'active') AS reference_count "
                "FROM personal_style p "
                "JOIN personal_style_version v "
                "ON v.style_id = p.id AND v.version = p.current_version "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY p.updated_at DESC, p.name, p.id",
                params,
            ).fetchall()
        finally:
            connection.close()
        records: list[PersonalStyleListItemRecord] = []
        for row in rows:
            head = _head_from_row(row)
            records.append(
                PersonalStyleListItemRecord(
                    head=head,
                    profile=_profile_from_row(row, status=head.status),
                    reference_count=int(row["reference_count"]),
                )
            )
        return records

    def add_version(
        self,
        profile: PersonalStyleProfile,
        definition: PersonalStyleDefinition,
        *,
        owner_id: str,
        change_source: PersonalStyleChangeSource,
        change_note: str | None = None,
    ) -> None:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version, source, owner_id FROM personal_style "
                "WHERE id = ? AND deleted_at IS NULL",
                (profile.id,),
            ).fetchone()
            if row is None or str(row["owner_id"]) != owner_id:
                raise PersonalStyleNotFoundError(
                    f"personal style '{profile.id}' does not exist for this owner"
                )
            if _version_key(profile.version) <= _version_key(str(row["current_version"])):
                raise PersonalStyleVersionConflictError(
                    f"version '{profile.version}' must be newer than '{row['current_version']}'"
                )
            if profile.personal.source.value != str(row["source"]):
                raise PersonalStyleVersionConflictError(
                    "personal style source cannot change between versions"
                )
            connection.execute(
                "INSERT INTO personal_style_version "
                "(style_id, version, profile_json, definition_json, change_source, "
                " change_note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.id,
                    profile.version,
                    profile.model_dump_json(by_alias=True),
                    definition.model_dump_json(by_alias=True),
                    change_source.value,
                    change_note,
                    now,
                ),
            )
            connection.execute(
                "UPDATE personal_style "
                "SET current_version = ?, name = ?, description = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ?",
                (
                    profile.version,
                    profile.name,
                    profile.description,
                    now,
                    profile.id,
                    owner_id,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            message = str(exc)
            if "personal_style.name" in message:
                raise DuplicatePersonalStyleNameError(
                    f"owner '{owner_id}' already has a personal style named '{profile.name}'"
                ) from exc
            raise PersonalStyleVersionConflictError(
                f"version '{profile.version}' already exists for '{profile.id}'"
            ) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_status(self, style_id: str, *, owner_id: str, status: PersonalStyleStatus) -> None:
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE personal_style SET status = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                (status.value, utc_now(), style_id, owner_id),
            )
            if cursor.rowcount == 0:
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
        finally:
            connection.close()

    def set_favorite(self, style_id: str, *, owner_id: str, favorite: bool) -> None:
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE personal_style SET favorite = ?, updated_at = ? "
                "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
                (int(favorite), utc_now(), style_id, owner_id),
            )
            if cursor.rowcount == 0:
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
        finally:
            connection.close()

    def delete(self, style_id: str, *, owner_id: str) -> DeletionStatus:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT owner_id FROM personal_style WHERE id = ?",
                (style_id,),
            ).fetchone()
            if row is None or str(row["owner_id"]) != owner_id:
                tombstone = connection.execute(
                    "SELECT 1 FROM personal_style_tombstone WHERE style_id = ? AND owner_id = ?",
                    (style_id, owner_id),
                ).fetchone()
                connection.rollback()
                return "tombstoned" if tombstone is not None else "missing"
            connection.execute("DELETE FROM personal_style WHERE id = ?", (style_id,))
            connection.execute(
                "INSERT OR REPLACE INTO personal_style_tombstone "
                "(style_id, owner_id, deleted_at) VALUES (?, ?, ?)",
                (style_id, owner_id, now),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return "deleted"

    def list_versions(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> list[PersonalStyleVersionRecord]:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return []
            rows = connection.execute(
                "SELECT version, change_source, change_note, created_at "
                "FROM personal_style_version WHERE style_id = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (style_id,),
            ).fetchall()
        finally:
            connection.close()
        return [
            PersonalStyleVersionRecord(
                version=str(row["version"]),
                change_source=PersonalStyleChangeSource(str(row["change_source"])),
                change_note=None if row["change_note"] is None else str(row["change_note"]),
                created_at=_parse_time(row["created_at"]),
            )
            for row in rows
        ]

    def get_version(
        self,
        style_id: str,
        version: str,
        *,
        owner_id: str,
    ) -> PersonalStyleRecord | None:
        return self.get(style_id, owner_id=owner_id, version=version)

    def add_references(
        self,
        style_id: str,
        *,
        owner_id: str,
        references: Sequence[PersonalStyleReference],
    ) -> list[PersonalStyleReference]:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not self._owns(connection, style_id, owner_id):
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
            for reference in references:
                if reference.image_id is None:
                    raise PersonalStyleReferenceNotFoundError(
                        "a reference photo must point at an existing image"
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO personal_style_reference "
                    "(id, style_id, image_id, image_sha256, analysis_id, original_name, "
                    " consent_scope, consent_at, status, added_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(reference.id),
                        style_id,
                        str(reference.image_id),
                        reference.image_sha256,
                        None if reference.analysis_id is None else str(reference.analysis_id),
                        reference.original_name,
                        reference.consent_scope.value,
                        _iso(reference.consent_at),
                        reference.status.value,
                        _iso(reference.added_at),
                    ),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.list_references(style_id, owner_id=owner_id)

    def list_references(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> list[PersonalStyleReference]:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return []
            rows = connection.execute(
                "SELECT * FROM personal_style_reference WHERE style_id = ? "
                "AND status IN ('active', 'missing') ORDER BY added_at, id",
                (style_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_reference_from_row(row) for row in rows]

    def get_reference(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
    ) -> PersonalStyleReference | None:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return None
            row = connection.execute(
                "SELECT * FROM personal_style_reference WHERE id = ? AND style_id = ?",
                (reference_id, style_id),
            ).fetchone()
        finally:
            connection.close()
        return _reference_from_row(row) if row is not None else None

    def set_reference_analysis(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
        analysis_id: str,
    ) -> None:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not self._owns(connection, style_id, owner_id):
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
            cursor = connection.execute(
                "UPDATE personal_style_reference SET analysis_id = ? WHERE id = ? AND style_id = ?",
                (analysis_id, reference_id, style_id),
            )
            if cursor.rowcount == 0:
                raise PersonalStyleReferenceNotFoundError(
                    f"reference '{reference_id}' does not belong to '{style_id}'"
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mark_reference_missing(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
    ) -> None:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
            connection.execute(
                "UPDATE personal_style_reference SET status = 'missing' "
                "WHERE id = ? AND style_id = ?",
                (reference_id, style_id),
            )
        finally:
            connection.close()

    def upsert_feature(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
        features: PhotoVisualFeatures,
    ) -> None:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not self._owns(connection, style_id, owner_id):
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
            reference = connection.execute(
                "SELECT image_sha256 FROM personal_style_reference WHERE id = ? AND style_id = ?",
                (reference_id, style_id),
            ).fetchone()
            if reference is None:
                raise PersonalStyleReferenceNotFoundError(
                    f"reference '{reference_id}' does not belong to '{style_id}'"
                )
            if str(reference["image_sha256"]) != features.image_sha256:
                raise PersonalStyleFeatureMismatchError(
                    "extracted features do not belong to the reference photo"
                )
            connection.execute(
                "INSERT INTO personal_style_photo_feature "
                "(reference_id, style_id, image_sha256, analysis_id, extractor_version, "
                " features_json, confidence, is_mock, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(reference_id) DO UPDATE SET "
                " image_sha256 = excluded.image_sha256, "
                " analysis_id = excluded.analysis_id, "
                " extractor_version = excluded.extractor_version, "
                " features_json = excluded.features_json, "
                " confidence = excluded.confidence, "
                " is_mock = excluded.is_mock, "
                " created_at = excluded.created_at",
                (
                    reference_id,
                    style_id,
                    features.image_sha256,
                    str(features.analysis_id),
                    features.extractor_version,
                    features.model_dump_json(by_alias=True),
                    features.overall_confidence,
                    int(features.is_mock),
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE personal_style_reference SET analysis_id = ? WHERE id = ? AND style_id = ?",
                (str(features.analysis_id), reference_id, style_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_feature(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
    ) -> PhotoVisualFeatures | None:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return None
            row = connection.execute(
                "SELECT f.features_json AS features_json "
                "FROM personal_style_photo_feature f "
                "JOIN personal_style_reference r ON r.id = f.reference_id "
                "WHERE f.reference_id = ? AND f.style_id = ? AND r.style_id = ?",
                (reference_id, style_id, style_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return PhotoVisualFeatures.model_validate_json(str(row["features_json"]))

    def list_features(
        self,
        style_id: str,
        *,
        owner_id: str,
    ) -> dict[str, PhotoVisualFeatures]:
        connection = connect(self._path)
        try:
            if not self._owns(connection, style_id, owner_id):
                return {}
            rows = connection.execute(
                "SELECT reference_id, features_json FROM personal_style_photo_feature "
                "WHERE style_id = ?",
                (style_id,),
            ).fetchall()
        finally:
            connection.close()
        return {
            str(row["reference_id"]): PhotoVisualFeatures.model_validate_json(
                str(row["features_json"])
            )
            for row in rows
        }

    def remove_reference(
        self,
        style_id: str,
        reference_id: str,
        *,
        owner_id: str,
    ) -> bool:
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not self._owns(connection, style_id, owner_id):
                raise PersonalStyleNotFoundError(
                    f"personal style '{style_id}' does not exist for this owner"
                )
            row = connection.execute(
                "SELECT 1 FROM personal_style_reference WHERE id = ? AND style_id = ?",
                (reference_id, style_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            connection.execute(
                "DELETE FROM personal_style_photo_feature WHERE reference_id = ?",
                (reference_id,),
            )
            connection.execute(
                "DELETE FROM personal_style_reference WHERE id = ? AND style_id = ?",
                (reference_id, style_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return True

    @staticmethod
    def _owns(connection: sqlite3.Connection, style_id: str, owner_id: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM personal_style WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
            (style_id, owner_id),
        ).fetchone()
        return row is not None


__all__ = [
    "DeletionStatus",
    "DuplicatePersonalStyleIdError",
    "DuplicatePersonalStyleNameError",
    "PersonalStyleFeatureMismatchError",
    "PersonalStyleHead",
    "PersonalStyleListItemRecord",
    "PersonalStyleNotFoundError",
    "PersonalStyleRecord",
    "PersonalStyleReferenceNotFoundError",
    "PersonalStyleVersionConflictError",
    "PersonalStyleVersionRecord",
    "SqlitePersonalStyleRepository",
]
