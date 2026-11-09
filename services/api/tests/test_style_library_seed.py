from __future__ import annotations

from pathlib import Path

import pytest

from app.models.photographer import StyleCategory
from app.models.style_profile import StyleKind, StyleProfile
from app.repositories.db import initialize_database
from app.repositories.style_repo import SqliteStyleProfileRepository
from app.styles.library import SEED_PROFILES, seed_style_library

MASTER_IDS = {
    "saul_leiter",
    "fan_ho",
    "ansel_adams",
    "henri_cartier_bresson",
    "vivian_maier",
    "william_eggleston",
    "steve_mccurry",
    "hiroshi_sugimoto",
}
GENRE_IDS = {
    "bw_documentary",
    "poetic_street",
    "cinematic_narrative",
    "retro_film",
    "minimal_architecture",
    "nature_landscape",
    "environmental_portrait",
    "night_photography",
}


@pytest.fixture
def repo(tmp_path: Path) -> SqliteStyleProfileRepository:
    path = tmp_path / "frame.db"
    initialize_database(path)
    return SqliteStyleProfileRepository(path)


def test_seed_catalog_shape() -> None:
    assert len(SEED_PROFILES) == 16
    ids = [profile.id for profile in SEED_PROFILES]
    assert len(set(ids)) == 16
    assert set(ids) == MASTER_IDS | GENRE_IDS
    masters = {p.id for p in SEED_PROFILES if p.kind is StyleKind.MASTER}
    genres = {p.id for p in SEED_PROFILES if p.kind is StyleKind.GENRE}
    assert masters == MASTER_IDS
    assert genres == GENRE_IDS
    assert all(p.version == "1.0" and p.enabled for p in SEED_PROFILES)


@pytest.mark.parametrize("profile", SEED_PROFILES, ids=lambda p: p.id)
def test_archive_content_is_complete(profile: StyleProfile) -> None:
    assert profile.description.strip()
    assert profile.philosophy.strip()
    assert profile.post_strategy.strip()
    assert profile.capture_techniques.strip()
    assert profile.preserve_notes.strip()
    assert profile.scene_fit.suitable
    assert profile.scene_fit.suitable_notes.strip()
    assert profile.scene_fit.unsuitable_notes.strip()
    assert profile.sources
    assert all(source.title.strip() and source.license.strip() for source in profile.sources)
    assert profile.constraints
    definition = profile.to_style_definition()
    assert definition.id == profile.id
    assert definition.supported_scenes == profile.scene_fit.suitable
    expected_category = (
        StyleCategory.CREATIVE if profile.kind is StyleKind.MASTER else StyleCategory.SCENE
    )
    assert definition.category is expected_category


def test_seed_into_empty_library(repo: SqliteStyleProfileRepository) -> None:
    result = seed_style_library(repo)
    assert len(result.created) == 16
    assert result.skipped == ()
    listed = repo.list_profiles()
    assert len(listed) == 16
    for profile in SEED_PROFILES:
        assert repo.get(profile.id) == profile


def test_seed_is_idempotent(repo: SqliteStyleProfileRepository) -> None:
    seed_style_library(repo)
    result = seed_style_library(repo)
    assert result.created == ()
    assert len(result.skipped) == 16
    assert len(repo.list_profiles()) == 16
    assert all(repo.list_versions(p.id) == ["1.0"] for p in SEED_PROFILES)


def test_seed_does_not_overwrite_user_changes(repo: SqliteStyleProfileRepository) -> None:
    seed_style_library(repo)
    edited = SEED_PROFILES[1].model_copy(
        update={"version": "1.1", "description": "用户修订后的档案描述。"}
    )
    repo.add_version(edited)
    repo.set_enabled("steve_mccurry", False)
    repo.add_favorite("fan_ho")

    result = seed_style_library(repo)
    assert result.created == ()
    assert len(result.skipped) == 16

    current = repo.get(edited.id)
    assert current is not None
    assert current.version == "1.1"
    assert current.description == "用户修订后的档案描述。"
    disabled = repo.get("steve_mccurry")
    assert disabled is not None
    assert disabled.enabled is False
    assert repo.list_favorites() == ["fan_ho"]
    assert len(repo.list_profiles()) == 16
