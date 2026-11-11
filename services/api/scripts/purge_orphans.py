from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.core.config import Settings  # noqa: E402
from app.tools.purge_orphans import apply_plan, build_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove orphaned originals/proxies and database rows whose original "
            "file is missing. Runs as a dry-run unless --apply is given."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the deletions; without it only counts are printed",
    )
    parser.add_argument(
        "--list-paths",
        action="store_true",
        help="print the paths that would be removed (local output only)",
    )
    args = parser.parse_args()

    settings = Settings()
    plan = build_plan(settings)
    print(f"data dir: {settings.data_dir}")
    print(f"orphan originals: {len(plan.orphan_originals)}")
    print(f"orphan proxies: {len(plan.orphan_proxies)}")
    print(f"orphan generated assets: {len(plan.orphan_generated)}")
    print(f"orphan generative results: {len(plan.orphan_results)}")
    print(f"orphan masks: {len(plan.orphan_masks)}")
    print(f"image records with missing original: {len(plan.dangling_images)}")
    if args.list_paths:
        for path in (
            *plan.orphan_originals,
            *plan.orphan_proxies,
            *plan.orphan_generated,
            *plan.orphan_results,
            *plan.orphan_masks,
        ):
            print(f"  file {path}")
        for image_id in plan.dangling_images:
            print(f"  record {image_id}")

    if not args.apply:
        print("dry-run: nothing changed (pass --apply to delete)")
        return 0

    report = apply_plan(settings, plan)
    print(
        "deleted: "
        f"{report.deleted_originals} originals, "
        f"{report.deleted_proxies} proxies, "
        f"{report.deleted_generated} generated, "
        f"{report.deleted_results} results, "
        f"{report.deleted_masks} masks, "
        f"{report.deleted_records} records; "
        f"skipped (locked/unremovable): {report.skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
