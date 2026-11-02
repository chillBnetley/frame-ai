from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.main import create_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET = REPO_ROOT / "shared" / "contracts" / "openapi.json"


def render_schema() -> str:
    schema = create_app().openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or verify the committed OpenAPI schema.")
    parser.add_argument(
        "--check", action="store_true", help="fail when the committed file is stale"
    )
    args = parser.parse_args()

    rendered = render_schema()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != rendered:
            print(
                f"{TARGET} is out of date. Run: python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"{TARGET} is up to date")
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
