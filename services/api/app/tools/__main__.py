from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import Settings
from app.tools.import_json_registry import import_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Import the legacy JSON image registry.")
    parser.add_argument(
        "--registry",
        type=str,
        default=None,
        help="Path to image_registry.json (default: FRAME_DATA_DIR/image_registry.json)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Keep the JSON registry in place instead of renaming it to .imported.bak",
    )
    args = parser.parse_args()

    settings = Settings()
    report = import_registry(
        settings,
        registry_path=settings.registry_path if args.registry is None else Path(args.registry),
        backup=not args.no_backup,
    )
    print(f"registry_found={report.registry_found}")
    print(f"imported={report.imported}")
    print(f"already_present={report.already_present}")
    print(f"skipped={len(report.skipped)}")
    for item in report.skipped:
        print(f"  skip {item.image_id}: {item.reason}")
    print(f"backup={report.backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
