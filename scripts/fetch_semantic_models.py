"""Explicitly download optional semantic-mask models (never runs automatically).

Example:
    services/api/.venv/Scripts/python.exe scripts/fetch_semantic_models.py \
        --class sky --data-dir C:/path/to/frame-data
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.imaging.semantic_models import (  # noqa: E402
    PERSON_SPEC,
    SKY_SPEC,
    ModelSpec,
    file_matches,
)


def _download(spec: ModelSpec, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".download")
    digest = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(spec_url(spec), timeout=120) as response:
        with temporary.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
    if written != spec.bytes or digest.hexdigest() != spec.sha256:
        temporary.unlink(missing_ok=True)
        raise SystemExit(
            f"{spec.kind}: downloaded bytes/hash do not match the manifest "
            f"(got {written} / {digest.hexdigest()})"
        )
    os.replace(temporary, target)
    return written


def spec_url(spec: ModelSpec) -> str:
    return spec.source_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--class",
        dest="semantic_class",
        choices=("person", "sky", "both"),
        default="both",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="FRAME_DATA_DIR (defaults to FRAME_DATA_DIR or <repo>/data)",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    data_dir = args.data_dir or Path(
        os.environ.get("FRAME_DATA_DIR") or REPO_ROOT / "data"
    )
    specs = [PERSON_SPEC, SKY_SPEC] if args.semantic_class == "both" else [
        PERSON_SPEC if args.semantic_class == "person" else SKY_SPEC
    ]
    for spec in specs:
        if spec.kind == "person":
            # Bundled with the repository; verify it instead of downloading.
            from app.imaging.semantic_models import SEMANTIC_DIR

            source = SEMANTIC_DIR / spec.filename
            if not file_matches(source, spec.bytes, spec.sha256):
                raise SystemExit(f"person: bundled model is missing or corrupt at {source}")
            print(f"person: bundled model verified ({spec.bytes} bytes)")
            continue
        target = data_dir / "models" / "semantic" / spec.filename
        if not args.force and file_matches(target, spec.bytes, spec.sha256):
            print(f"sky: already present and verified at {target}")
            continue
        print(f"sky: downloading {spec.bytes} bytes from {spec_url(spec)}")
        written = _download(spec, target)
        print(f"sky: wrote {written} bytes to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
