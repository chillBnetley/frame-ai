from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.models.style_profile import StyleKind, StyleProfile
from app.repositories.db import connect, initialize_database
from app.repositories.style_repo import (
    DuplicateStyleProfileError,
    SqliteStyleProfileRepository,
    StyleProfileNotFoundError,
    StyleVersionConflictError,
)


def _profile(**overrides: Any) -> StyleProfile:
    data: dict[str, Any] = {
        "id": "fan_ho",
        "kind": "master",
        "name": "Fan Ho 灵感",
        "description": "光影几何街头档案。",
        "philosophy": "以光为笔，捕捉明暗交界的瞬间。",
        "color": {"tendency": "克制", "relationships": "低饱和互补", "saturation": "偏低"},
        "light": {
            "contrast": "高对比",
            "shadows": "深",
            "highlights": "集中",
            "expression": "硬光",
        },
        "composition": {
            "space": "分割",
            "geometry": "几何",
            "negative_space": "留白",
            "subject_relation": "光区主体",
        },
        "texture": {"grain": "细", "sharpness": "中", "detail": "层次"},
        "scene_fit": {
            "suitable": ["street"],
            "suitable_notes": "方向光街头",
            "unsuitable_notes": "平光",
        },
        "post_strategy": "曝光对比曲线与局部明暗。",
        "capture_techniques": "不能创造光源与瞬间。",
        "preserve_notes": "保护人物与光线关系。",
        "sources": [{"title": "研究参考", "license": "原创整理"}],
        "engine_style": "street",
    }
    data.update(overrides)
    return StyleProfile.model_validate(data)


@pytest.fixture
def repo(tmp_path: Path) -> SqliteStyleProfileRepository:
    path = tmp_path / "frame.db"
    initialize_database(path)
    return SqliteStyleProfileRepository(path)


def test_migration_creates_style_tables(tmp_path: Path) -> None:
    path = tmp_path / "frame.db"
    initialize_database(path)
    connection = connect(path)
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
    assert {"style_profile", "style_profile_version", "style_favorite", "image_asset"} <= tables
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert issues == []


def test_create_and_get_current(repo: SqliteStyleProfileRepository) -> None:
    profile = _profile()
    repo.create(profile)
    assert repo.get("fan_ho") == profile
    assert repo.list_versions("fan_ho") == ["1.0"]


def test_get_missing_returns_none(repo: SqliteStyleProfileRepository) -> None:
    assert repo.get("missing") is None
    assert repo.get("missing", version="1.0") is None
    assert repo.list_profiles() == []
    assert repo.list_versions("missing") == []


def test_create_duplicate_is_atomic(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    with pytest.raises(DuplicateStyleProfileError):
        repo.create(_profile(name="另一个名字"))
    current = repo.get("fan_ho")
    assert current is not None
    assert current.name == "Fan Ho 灵感"
    assert repo.list_versions("fan_ho") == ["1.0"]


def test_list_filters_and_search(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    repo.create(_profile(id="bw_documentary", kind="genre", name="黑白纪实", enabled=False))
    assert len(repo.list_profiles()) == 2
    masters = repo.list_profiles(kind=StyleKind.MASTER)
    assert [p.id for p in masters] == ["fan_ho"]
    assert [p.id for p in repo.list_profiles(enabled_only=True)] == ["fan_ho"]
    assert [p.id for p in repo.list_profiles(search="Fan")] == ["fan_ho"]
    assert [p.id for p in repo.list_profiles(search="fan_ho")] == ["fan_ho"]
    assert [p.id for p in repo.list_profiles(search="黑白")] == ["bw_documentary"]
    disabled = repo.get("bw_documentary")
    assert disabled is not None
    assert disabled.enabled is False


def test_search_escapes_like_wildcards(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile(id="genre_film", kind="genre", name="100%_胶片"))
    repo.create(_profile(id="pure_film", kind="genre", name="纯胶片"))
    repo.create(_profile(id="nature", kind="genre", name="自然风光"))
    assert [p.id for p in repo.list_profiles(search="100%")] == ["genre_film"]
    assert {p.id for p in repo.list_profiles(search="_")} == {"genre_film", "pure_film"}
    assert len(repo.list_profiles(search="胶片")) == 2


def test_add_version_bumps_and_keeps_history(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    repo.add_version(_profile(version="1.1", name="Fan Ho 灵感 II", description="修订档案。"))
    current = repo.get("fan_ho")
    assert current is not None
    assert current.version == "1.1"
    assert current.name == "Fan Ho 灵感 II"
    assert current.description == "修订档案。"
    old = repo.get("fan_ho", version="1.0")
    assert old is not None
    assert old.name == "Fan Ho 灵感"
    assert old.description == "光影几何街头档案。"
    assert repo.list_versions("fan_ho") == ["1.1", "1.0"]
    listed = repo.list_profiles()
    assert len(listed) == 1
    assert listed[0].version == "1.1"


def test_add_version_rejects_stale_and_kind_change(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    with pytest.raises(StyleVersionConflictError):
        repo.add_version(_profile(version="1.0"))
    with pytest.raises(StyleVersionConflictError):
        repo.add_version(_profile(version="0.9"))
    with pytest.raises(StyleVersionConflictError):
        repo.add_version(_profile(version="1.1", kind="genre"))
    repo.add_version(_profile(version="2.0"))
    assert repo.list_versions("fan_ho") == ["2.0", "1.0"]


def test_add_version_unknown_profile(repo: SqliteStyleProfileRepository) -> None:
    with pytest.raises(StyleProfileNotFoundError):
        repo.add_version(_profile(id="missing", version="1.1"))


def test_add_version_preserves_head_enabled(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    repo.set_enabled("fan_ho", False)
    repo.add_version(_profile(version="1.1"))
    current = repo.get("fan_ho")
    assert current is not None
    assert current.enabled is False
    snapshot = repo.get("fan_ho", version="1.1")
    assert snapshot is not None
    assert snapshot.enabled is False
    original = repo.get("fan_ho", version="1.0")
    assert original is not None
    assert original.enabled is True


def test_set_enabled_toggle_and_missing(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    repo.set_enabled("fan_ho", False)
    current = repo.get("fan_ho")
    assert current is not None
    assert current.enabled is False
    assert repo.list_profiles(enabled_only=True) == []
    repo.set_enabled("fan_ho", True)
    current = repo.get("fan_ho")
    assert current is not None
    assert current.enabled is True
    with pytest.raises(StyleProfileNotFoundError):
        repo.set_enabled("missing", True)


def test_favorites(repo: SqliteStyleProfileRepository) -> None:
    repo.create(_profile())
    repo.create(_profile(id="bw_documentary", kind="genre", name="黑白纪实"))
    with pytest.raises(StyleProfileNotFoundError):
        repo.add_favorite("missing")
    repo.add_favorite("fan_ho")
    repo.add_favorite("fan_ho")
    repo.add_favorite("bw_documentary")
    assert set(repo.list_favorites()) == {"fan_ho", "bw_documentary"}
    repo.remove_favorite("fan_ho")
    repo.remove_favorite("fan_ho")
    assert repo.list_favorites() == ["bw_documentary"]
    repo.remove_favorite("missing")
    assert repo.list_favorites() == ["bw_documentary"]


def test_delete_profile_cascades(repo: SqliteStyleProfileRepository, tmp_path: Path) -> None:
    repo.create(_profile())
    repo.add_favorite("fan_ho")
    connection = connect(tmp_path / "frame.db")
    try:
        connection.execute("DELETE FROM style_profile WHERE id = 'fan_ho'")
    finally:
        connection.close()
    assert repo.get("fan_ho") is None
    assert repo.list_versions("fan_ho") == []
    assert repo.list_favorites() == []
