from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "services" / "api"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.core.config import Settings  # noqa: E402
from app.tools.backup_data import (  # noqa: E402
    BackupError,
    create_backup,
    verify_backup,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Back up the FRAME AI data directory (database, originals, masks, "
            "generated assets and provider configuration). Previews and exports "
            "are regenerable and excluded by default. The API token is never copied."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="source data directory; defaults to FRAME_DATA_DIR or <repo>/data",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="new directory to write the backup into; must not exist",
    )
    parser.add_argument(
        "--include-previews",
        action="store_true",
        help="also copy the regenerable preview and proxy cache",
    )
    parser.add_argument(
        "--include-models",
        action="store_true",
        help="also copy downloaded semantic model weights",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="verify an existing backup directory instead of creating one",
    )
    args = parser.parse_args()

    if args.verify is not None:
        report = verify_backup(args.verify)
        if report.ok:
            print(f"backup_verified entries={report.entries}")
            return 0
        print(f"backup_invalid entries={report.entries}")
        for problem in report.problems:
            print(f"  - {problem}")
        return 1

    if args.output is None:
        parser.error("--output is required unless --verify is used")

    settings = Settings()
    source = args.data_dir or settings.data_dir
    try:
        result = create_backup(
            source,
            args.output,
            database_filename=settings.database_filename,
            include_previews=args.include_previews,
            include_models=args.include_models,
        )
    except BackupError as error:
        print(f"backup_failed: {error}")
        return 1

    print(f"backup_written path={result.destination}")
    print(f"backup_entries={len(result.entries)} bytes={result.total_bytes}")
    print(f"backup_db_version={result.db_version}")
    for name, count in result.counts.items():
        print(f"  {name}={count}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
