from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from app.models.style_profile import StyleKind, StyleProfile
from app.repositories.db import connect, utc_now


class StyleProfileNotFoundError(LookupError):
    """The requested style profile does not exist."""


class DuplicateStyleProfileError(ValueError):
    """A style profile with the same id already exists."""


class StyleVersionConflictError(ValueError):
    """The new version is not strictly newer, or changes immutable fields."""


def _version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def _like_pattern(search: str) -> str:
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _parse_profile(row: sqlite3.Row, *, enabled: bool | None = None) -> StyleProfile:
    profile = StyleProfile.model_validate_json(str(row["profile_json"]))
    # Enabled is head state, not version content: overlay it on current reads
    # so toggling never rewrites stored archive snapshots.
    if enabled is not None and profile.enabled != enabled:
        profile = profile.model_copy(update={"enabled": enabled})
    return profile


class SqliteStyleProfileRepository:
    def __init__(self, path: Path) -> None:
        self._path = path

    def create(self, profile: StyleProfile) -> None:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO style_profile "
                "(id, kind, name, current_version, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    profile.id,
                    profile.kind.value,
                    profile.name,
                    profile.version,
                    int(profile.enabled),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO style_profile_version (style_id, version, profile_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (profile.id, profile.version, profile.model_dump_json(by_alias=True), now),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise DuplicateStyleProfileError(
                f"style profile '{profile.id}' already exists"
            ) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_many(self, profiles: Sequence[StyleProfile]) -> set[str]:
        """Insert the profiles that are still missing in one transaction."""
        now = utc_now()
        created: set[str] = set()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for profile in profiles:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO style_profile "
                    "(id, kind, name, current_version, enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        profile.id,
                        profile.kind.value,
                        profile.name,
                        profile.version,
                        int(profile.enabled),
                        now,
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    continue
                connection.execute(
                    "INSERT INTO style_profile_version "
                    "(style_id, version, profile_json, created_at) VALUES (?, ?, ?, ?)",
                    (profile.id, profile.version, profile.model_dump_json(by_alias=True), now),
                )
                created.add(profile.id)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return created

    def get(self, style_id: str, *, version: str | None = None) -> StyleProfile | None:
        connection = connect(self._path)
        try:
            if version is None:
                row = connection.execute(
                    "SELECT v.profile_json AS profile_json, p.enabled AS enabled "
                    "FROM style_profile p "
                    "JOIN style_profile_version v "
                    "ON v.style_id = p.id AND v.version = p.current_version "
                    "WHERE p.id = ?",
                    (style_id,),
                ).fetchone()
                return _parse_profile(row, enabled=bool(row["enabled"])) if row else None
            row = connection.execute(
                "SELECT profile_json FROM style_profile_version WHERE style_id = ? AND version = ?",
                (style_id, version),
            ).fetchone()
            return _parse_profile(row) if row else None
        finally:
            connection.close()

    def list_profiles(
        self,
        *,
        kind: StyleKind | None = None,
        enabled_only: bool = False,
        search: str | None = None,
    ) -> list[StyleProfile]:
        clauses = ["1 = 1"]
        params: list[object] = []
        if kind is not None:
            clauses.append("p.kind = ?")
            params.append(kind.value)
        if enabled_only:
            clauses.append("p.enabled = 1")
        if search is not None and search.strip():
            clauses.append("(p.name LIKE ? ESCAPE '\\' OR p.id LIKE ? ESCAPE '\\')")
            pattern = _like_pattern(search.strip())
            params.extend([pattern, pattern])
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT v.profile_json AS profile_json, p.enabled AS enabled "
                "FROM style_profile p "
                "JOIN style_profile_version v "
                "ON v.style_id = p.id AND v.version = p.current_version "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY p.kind, p.name, p.id",
                params,
            ).fetchall()
        finally:
            connection.close()
        return [_parse_profile(row, enabled=bool(row["enabled"])) for row in rows]

    def add_version(self, profile: StyleProfile) -> None:
        now = utc_now()
        connection = connect(self._path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version, kind, enabled FROM style_profile WHERE id = ?",
                (profile.id,),
            ).fetchone()
            if row is None:
                raise StyleProfileNotFoundError(f"style profile '{profile.id}' does not exist")
            if _version_key(profile.version) <= _version_key(str(row["current_version"])):
                raise StyleVersionConflictError(
                    f"version '{profile.version}' must be newer than '{row['current_version']}'"
                )
            if profile.kind.value != str(row["kind"]):
                raise StyleVersionConflictError("style kind cannot change between versions")
            stored = profile.model_copy(update={"enabled": bool(row["enabled"])})
            connection.execute(
                "INSERT INTO style_profile_version (style_id, version, profile_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (profile.id, profile.version, stored.model_dump_json(by_alias=True), now),
            )
            connection.execute(
                "UPDATE style_profile SET current_version = ?, name = ?, updated_at = ? "
                "WHERE id = ?",
                (profile.version, profile.name, now, profile.id),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise StyleVersionConflictError(
                f"version '{profile.version}' already exists for '{profile.id}'"
            ) from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_enabled(self, style_id: str, enabled: bool) -> None:
        connection = connect(self._path)
        try:
            cursor = connection.execute(
                "UPDATE style_profile SET enabled = ?, updated_at = ? WHERE id = ?",
                (int(enabled), utc_now(), style_id),
            )
            if cursor.rowcount == 0:
                raise StyleProfileNotFoundError(f"style profile '{style_id}' does not exist")
        finally:
            connection.close()

    def list_versions(self, style_id: str) -> list[str]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT version FROM style_profile_version WHERE style_id = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (style_id,),
            ).fetchall()
        finally:
            connection.close()
        return [str(row["version"]) for row in rows]

    def add_favorite(self, style_id: str) -> None:
        connection = connect(self._path)
        try:
            row = connection.execute(
                "SELECT 1 FROM style_profile WHERE id = ?", (style_id,)
            ).fetchone()
            if row is None:
                raise StyleProfileNotFoundError(f"style profile '{style_id}' does not exist")
            connection.execute(
                "INSERT OR IGNORE INTO style_favorite (style_id, created_at) VALUES (?, ?)",
                (style_id, utc_now()),
            )
        finally:
            connection.close()

    def remove_favorite(self, style_id: str) -> None:
        connection = connect(self._path)
        try:
            connection.execute("DELETE FROM style_favorite WHERE style_id = ?", (style_id,))
        finally:
            connection.close()

    def list_favorites(self) -> list[str]:
        connection = connect(self._path)
        try:
            rows = connection.execute(
                "SELECT style_id FROM style_favorite ORDER BY created_at DESC, style_id"
            ).fetchall()
        finally:
            connection.close()
        return [str(row["style_id"]) for row in rows]
