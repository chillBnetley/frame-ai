#!/usr/bin/env python3
"""Run every Phase 2 regression gate and print an exit-code table.

Usage (from any directory):
    services/api/.venv/Scripts/python.exe scripts/verify.py

The script exits 0 only when every gate exits 0. Full output of failing gates
is printed below the table.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"


@dataclass(frozen=True)
class Gate:
    name: str
    command: list[str]
    cwd: Path


def _npm() -> list[str]:
    if os.name == "nt":
        return ["cmd.exe", "/c", "npm"]
    return [shutil.which("npm") or "npm"]


def _gates() -> list[Gate]:
    python = sys.executable
    npm = _npm()
    return [
        Gate("ruff check", [python, "-m", "ruff", "check", "."], API_DIR),
        Gate("ruff format --check", [python, "-m", "ruff", "format", "--check", "."], API_DIR),
        Gate("mypy app", [python, "-m", "mypy", "app"], API_DIR),
        Gate("pytest", [python, "-m", "pytest", "-q"], API_DIR),
        Gate("openapi sync", [python, "scripts/export_openapi.py", "--check"], API_DIR),
        Gate("npm lint", [*npm, "run", "lint"], WEB_DIR),
        Gate("npm typecheck", [*npm, "run", "typecheck"], WEB_DIR),
        Gate("npm test", [*npm, "run", "test"], WEB_DIR),
        Gate("npm check:api", [*npm, "run", "check:api"], WEB_DIR),
        Gate("npm build", [*npm, "run", "build"], WEB_DIR),
    ]


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except OSError as exc:
        return f"(git unavailable: {exc})"
    return result.stdout.strip() or "(empty)"


def _summary(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    return " | ".join(lines[-2:])[:160]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    environment = {
        **os.environ,
        "CI": "1",
        "NEXT_TELEMETRY_DISABLED": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    print(f"FRAME AI verification - {datetime.now().astimezone().isoformat(timespec='seconds')}")
    print(f"root:   {ROOT}")
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    print(f"commit: {_git('rev-parse', 'HEAD')}")
    print(f"status: {_git('status', '--short').replace(chr(10), ', ')}")
    print()

    rows: list[tuple[str, str, int, str, str]] = []
    failures: list[tuple[Gate, str]] = []

    for gate in _gates():
        relative_cwd = gate.cwd.relative_to(ROOT).as_posix() or "."
        started = time.perf_counter()
        try:
            result = subprocess.run(
                gate.command,
                cwd=gate.cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            output = f"{result.stdout}\n{result.stderr}"
            exit_code = result.returncode
        except subprocess.TimeoutExpired as exc:
            output = f"timed out after {exc.timeout} seconds"
            exit_code = 124
        duration = f"{time.perf_counter() - started:.1f}s"

        status = "PASS" if exit_code == 0 else "FAIL"
        rows.append((gate.name, relative_cwd, exit_code, duration, _summary(output)))
        if exit_code != 0:
            failures.append((gate, output))
        print(f"[{status}] {gate.name} (exit {exit_code}, {duration})", flush=True)

    print()
    print("| gate | cwd | exit code | duration | summary |")
    print("| --- | --- | --- | --- | --- |")
    for name, cwd, exit_code, duration, summary in rows:
        print(f"| {name} | `{cwd}` | {exit_code} | {duration} | {summary} |")

    for gate, output in failures:
        print()
        print(f"===== FAILED: {gate.name} ({' '.join(gate.command)}) =====")
        print(output.rstrip())

    failed = len(failures)
    print()
    print(f"{len(rows) - failed}/{len(rows)} gates passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
