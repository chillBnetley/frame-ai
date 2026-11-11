from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.imaging.loader import PROXY_EDGE_STEP, proxy_cache_directory, proxy_cache_path
from app.repositories.deletion_repo import SqliteDeletionRepository, StoredImageRecord

logger = logging.getLogger("frame_ai.purge")


@dataclass(frozen=True)
class PurgePlan:
    """Files and rows that a purge run would remove.

    A plan only names paths; nothing is deleted until ``apply_plan`` runs, so
    ``--dry-run`` can report exact counts without touching user data.
    """

    orphan_originals: tuple[Path, ...]
    orphan_proxies: tuple[Path, ...]
    dangling_images: tuple[str, ...]
    orphan_generated: tuple[Path, ...] = ()
    orphan_results: tuple[Path, ...] = ()
    orphan_masks: tuple[Path, ...] = ()

    @property
    def total_files(self) -> int:
        return (
            len(self.orphan_originals)
            + len(self.orphan_proxies)
            + len(self.orphan_generated)
            + len(self.orphan_results)
            + len(self.orphan_masks)
        )


@dataclass(frozen=True)
class PurgeReport:
    deleted_originals: int = 0
    deleted_proxies: int = 0
    deleted_records: int = 0
    deleted_generated: int = 0
    deleted_results: int = 0
    deleted_masks: int = 0
    skipped: int = 0


def build_plan(
    settings: Settings,
    *,
    repository: SqliteDeletionRepository | None = None,
) -> PurgePlan:
    repo = repository or SqliteDeletionRepository(settings.database_path)
    records = repo.list_images()

    referenced_names: set[str] = set()
    dangling: list[str] = []
    for record in records:
        path = _resolve_original(settings, record)
        if path is None:
            dangling.append(record.id)
            continue
        referenced_names.add(path.name)

    orphan_originals = tuple(
        sorted(
            path
            for path in _iter_files(settings.originals_dir)
            if path.name not in referenced_names
        )
    )

    # Dangling rows have no readable original; their proxies are derived data
    # of a record that is about to be removed, so they must be purged too.
    dangling_ids = set(dangling)
    expected_proxies: set[str] = set()
    for record in records:
        if record.id in dangling_ids:
            continue
        expected_proxies.update(_expected_proxy_names(settings, record))
    proxy_dir = proxy_cache_directory(settings.preview_dir)
    orphan_proxies = tuple(
        sorted(path for path in _iter_files(proxy_dir) if path.name not in expected_proxies)
    )
    live_generated = repo.list_live_generated_keys()
    orphan_generated = tuple(
        sorted(
            path
            for path in _iter_files(settings.generated_dir)
            if f"{settings.generated_dirname}/{path.name}" not in live_generated
        )
    )
    live_results = repo.list_live_result_keys()
    orphan_results = tuple(
        sorted(
            path
            for path in _iter_files(settings.generative_results_dir)
            if f"{settings.generative_results_dirname}/{path.name}" not in live_results
        )
    )
    live_masks = repo.list_live_mask_keys()
    orphan_masks = tuple(
        sorted(
            path
            for path in _iter_files(settings.data_dir / "masks")
            if f"masks/{path.name}" not in live_masks
        )
    )
    return PurgePlan(
        orphan_originals=orphan_originals,
        orphan_proxies=orphan_proxies,
        dangling_images=tuple(sorted(dangling)),
        orphan_generated=orphan_generated,
        orphan_results=orphan_results,
        orphan_masks=orphan_masks,
    )


def apply_plan(
    settings: Settings,
    plan: PurgePlan,
    *,
    repository: SqliteDeletionRepository | None = None,
) -> PurgeReport:
    repo = repository or SqliteDeletionRepository(settings.database_path)
    deleted_originals = _unlink_all(plan.orphan_originals)
    deleted_proxies = _unlink_all(plan.orphan_proxies)
    deleted_generated = _unlink_all(plan.orphan_generated)
    deleted_results = _unlink_all(plan.orphan_results)
    deleted_masks = _unlink_all(plan.orphan_masks)
    skipped = (
        len(plan.orphan_originals)
        - deleted_originals
        + len(plan.orphan_proxies)
        - deleted_proxies
        + len(plan.orphan_generated)
        - deleted_generated
        + len(plan.orphan_results)
        - deleted_results
        + len(plan.orphan_masks)
        - deleted_masks
    )
    deleted_records = 0
    for image_id in plan.dangling_images:
        outcome = repo.delete_image(image_id)
        if outcome.status == "deleted":
            deleted_records += 1
        elif outcome.status == "tombstoned":
            deleted_records += 1
    report = PurgeReport(
        deleted_originals=deleted_originals,
        deleted_proxies=deleted_proxies,
        deleted_records=deleted_records,
        deleted_generated=deleted_generated,
        deleted_results=deleted_results,
        deleted_masks=deleted_masks,
        skipped=skipped,
    )
    logger.info(
        "purge_applied originals=%s proxies=%s generated=%s results=%s masks=%s "
        "records=%s skipped=%s",
        report.deleted_originals,
        report.deleted_proxies,
        report.deleted_generated,
        report.deleted_results,
        report.deleted_masks,
        report.deleted_records,
        report.skipped,
    )
    return report


def _resolve_original(settings: Settings, record: StoredImageRecord) -> Path | None:
    try:
        candidate = (settings.data_dir / record.storage_key).resolve()
    except OSError:
        return None
    originals_dir = settings.originals_dir.resolve()
    if originals_dir not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _expected_proxy_names(settings: Settings, record: StoredImageRecord) -> set[str]:
    cache_dir = proxy_cache_directory(settings.preview_dir)
    limit = settings.render_max_edge_limit + PROXY_EDGE_STEP
    return {
        proxy_cache_path(cache_dir, record.sha256, edge).name
        for edge in range(PROXY_EDGE_STEP, limit, PROXY_EDGE_STEP)
    }


def _iter_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        logger.warning("purge_scan_failed directory=%s", directory)
        return []
    for entry in entries:
        try:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if entry.is_file():
                files.append(entry)
        except OSError:
            continue
    return files


def _unlink_all(paths: tuple[Path, ...]) -> int:
    deleted = 0
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            deleted += 1
        except OSError:
            logger.warning("purge_unlink_failed path=%s", path)
        else:
            deleted += 1
    return deleted


__all__ = ["PurgePlan", "PurgeReport", "apply_plan", "build_plan"]
