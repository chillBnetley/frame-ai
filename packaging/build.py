"""Build the portable Windows package for FRAME AI.

Usage (from the repository root, with the API virtualenv active):
    services/api/.venv/Scripts/python.exe packaging/build.py

Stages the traced Next.js server and a standalone Node runtime, runs
PyInstaller with ``packaging/frame-ai.spec``, then audits the result for any
database, image data, token, key, backup or dotenv file before finishing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
STAGE = ROOT / "packaging" / "out"
DIST = ROOT / "dist"
WORK = ROOT / ".pyinstaller"
APP_NAME = "FRAME AI"
SEMANTIC_DIR = ROOT / "services" / "api" / "app" / "imaging" / "semantic"
SEMANTIC_MANIFEST = json.loads((SEMANTIC_DIR / "manifest.json").read_text(encoding="utf-8"))

FORBIDDEN_NAMES = {
    "frame.db",
    "frame.db-wal",
    "frame.db-shm",
    "api-token",
    "provider-settings.json",
    "provider-master-key",
    "onboarding.json",
    ".env",
    "image_registry.json",
}
FORBIDDEN_SUFFIXES = {".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3"}
FORBIDDEN_DIRS = {
    "data",
    "eval-data",
    "visual-acceptance",
    "visual-inspect",
    "playwright-report",
    "test-results",
    "backups",
}


def log(message: str) -> None:
    print(f"[build] {message}", flush=True)


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    log(" ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sky_candidates() -> list[Path]:
    spec = SEMANTIC_MANIFEST["models"]["sky"]
    public = Path(os.environ.get("PUBLIC") or "C:/Users/Public")
    candidates = [
        ROOT / "data" / "models" / "semantic" / spec["file"],
        public / "FRAME-AI" / "models" / spec["sha256"] / spec["file"],
        ROOT / "data" / "visual-acceptance" / "models" / "semantic" / spec["file"],
    ]
    configured = os.environ.get("FRAME_SKY_MODEL", "").strip()
    if configured:
        candidates.insert(0, Path(configured))
    return candidates


def stage_semantic_models() -> None:
    """Copy the optional sky model only when its bytes match the manifest."""

    spec = SEMANTIC_MANIFEST["models"]["sky"]
    destination_dir = STAGE / "semantic"
    destination_dir.mkdir(parents=True)
    source: Path | None = None
    for candidate in _sky_candidates():
        if not candidate.is_file() or candidate.stat().st_size != int(spec["bytes"]):
            continue
        if _sha256(candidate) == spec["sha256"]:
            source = candidate
            break
    if source is None:
        raise SystemExit(
            "sky model not found or failed SHA-256 verification; run "
            "services/api/.venv/Scripts/python.exe scripts/fetch_semantic_models.py "
            "--class sky --data-dir <FRAME_DATA_DIR> or set FRAME_SKY_MODEL"
        )
    shutil.copy2(source, destination_dir / spec["file"])
    shutil.copy2(SEMANTIC_DIR / spec["licenseFile"], destination_dir / spec["licenseFile"])
    log(f"staged sky model from {source} ({spec['bytes']} bytes)")


def build_web() -> None:
    env = {
        **os.environ,
        "NEXT_STANDALONE": "1",
        "NEXT_TELEMETRY_DISABLED": "1",
        # Baked into the standalone rewrites; the launcher fails fast if busy.
        "API_INTERNAL_URL": "http://127.0.0.1:8000",
    }
    npm = ["cmd.exe", "/c", "npm"] if os.name == "nt" else ["npm"]
    run([*npm, "run", "build"], WEB, env)


def _prune_nsis_unsafe_cache(web_root: Path) -> None:
    """Drop regenerable PPR cache paths that NSIS cannot archive.

    Turbopack writes dynamic-segment cache names containing ``$``; NSIS treats
    those as variables when building the installer. The routes were verified to
    render correctly without these cache directories, so remove them from the
    packaged bundle (the server recreates what it needs at runtime).
    """

    route_cache = web_root / ".next" / "server" / "route-cache"
    if route_cache.is_dir():
        shutil.rmtree(route_cache)
        log("removed regenerable route-cache from the web bundle")

    removed = 0
    for path in sorted(web_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if "$" not in path.name or not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed += 1
    if removed:
        log(f"removed {removed} dollar-named cache paths from the web bundle")
    remaining = [path for path in web_root.rglob("*") if "$" in path.name]
    if remaining:
        raise SystemExit(f"NSIS-unsafe paths remain in the web bundle: {remaining[0]}")


def stage() -> None:
    # Turbopack's standalone tracing can follow the proxy's fs reads and copy
    # the repository data directory into .next/standalone. The package only
    # copies the apps/web subtree, and these copies are build junk that must
    # not linger next to the sources.
    standalone = WEB / ".next" / "standalone"
    for stray in (standalone / "data", standalone / "eval-data"):
        if stray.is_dir():
            log(f"removing traced data copy: {stray}")
            shutil.rmtree(stray)
    for dotenv in standalone.glob(".env*"):
        dotenv.unlink()

    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "node").mkdir(parents=True)
    log("staging traced Next.js server")
    server_root = WEB / ".next" / "standalone" / "apps" / "web"
    if not (server_root / "server.js").is_file():
        raise SystemExit(f"standalone server missing: {server_root}")
    shutil.copytree(
        server_root,
        STAGE / "web",
        ignore=shutil.ignore_patterns("tests", "test-results", "playwright-report", "data"),
    )
    shutil.copytree(WEB / ".next" / "static", STAGE / "web" / ".next" / "static")
    if (WEB / "public").is_dir():
        shutil.copytree(WEB / "public", STAGE / "web" / "public", dirs_exist_ok=True)
    _prune_nsis_unsafe_cache(STAGE / "web")

    node = shutil.which("node")
    if not node:
        raise SystemExit("node.exe not found on PATH")
    shutil.copy2(node, STAGE / "node" / "node.exe")
    log(f"staged node runtime from {node}")
    stage_semantic_models()


def package() -> None:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "packaging" / "frame-ai.spec"),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
        ],
        ROOT,
    )


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def audit() -> None:
    app_dir = DIST / APP_NAME
    if not (app_dir / f"{APP_NAME}.exe").is_file():
        raise SystemExit(f"executable missing: {app_dir / (APP_NAME + '.exe')}")
    if not (app_dir / "_internal" / "web" / "server.js").is_file():
        raise SystemExit("web bundle missing from the packaged app")
    if not (app_dir / "_internal" / "node" / "node.exe").is_file():
        raise SystemExit("node runtime missing from the packaged app")

    token_needle = b""
    token_file = ROOT / "data" / "api-token"
    if token_file.is_file():
        token_needle = token_file.read_bytes().strip()

    problems: list[str] = []
    for path in _iter_files(app_dir):
        relative = path.relative_to(app_dir)
        parts = relative.parts
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"forbidden file: {relative}")
        if parts and parts[0] in FORBIDDEN_DIRS:
            problems.append(f"forbidden directory entry: {relative}")
        if len(parts) >= 3 and parts[0] == "_internal" and parts[1] == "web" and parts[2] in FORBIDDEN_DIRS:
            problems.append(f"forbidden directory entry: {relative}")
        if path.name.startswith(".env"):
            problems.append(f"dotenv file: {relative}")
        if token_needle and path.stat().st_size < 64 * 1024 * 1024:
            try:
                if token_needle in path.read_bytes():
                    problems.append(f"api token bytes found in: {relative}")
            except OSError:
                pass

    if problems:
        for problem in problems:
            log(f"AUDIT FAIL {problem}")
        raise SystemExit(f"{len(problems)} forbidden entries in the package")

    total = sum(path.stat().st_size for path in _iter_files(app_dir))
    log(f"audit passed: {app_dir} ({total / 1024 / 1024:.1f} MiB)")


def main() -> int:
    if "--audit-only" in sys.argv[1:]:
        audit()
        return 0
    build_web()
    stage()
    package()
    audit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
