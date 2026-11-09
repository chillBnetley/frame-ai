#!/usr/bin/env python3
"""Read-only deployment preflight for V6.1.

Checks the resolved settings, data directories, migration version, provider
configuration, auth token, and optional semantic models. It never prints API
keys and never writes to the data directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

from app.core.config import Settings
from app.imaging.semantic_models import SemanticModelRegistry

EXPECTED_MIGRATION = 9


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def migration_version(database: Path) -> int | None:
    if not database.is_file():
        return None
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        return None if row is None or row[0] is None else int(row[0])
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def provider_configured(settings: Settings, kind: str) -> bool:
    provider = getattr(settings, f"{kind}_provider")
    if provider in (None, "mock"):
        return True
    key_field = getattr(settings, f"{kind}_api_key")
    key = "" if key_field is None else key_field.get_secret_value()
    if key:
        return True
    return (settings.data_dir / "provider-settings.json").is_file()


def run(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    data = settings.data_dir
    checks.append(
        Check(
            "data directory",
            "PASS" if data.is_dir() and os.access(data, os.W_OK) else "FAIL",
            f"{data} exists={data.is_dir()} writable={os.access(data, os.W_OK)}",
        )
    )
    if not data.exists():
        checks.append(
            Check("first start", "WARN", "data directory will be created on startup")
        )
    else:
        for name in ("originals", "mattes", "tmp/previews", "tmp/exports"):
            path = data / name
            checks.append(
                Check(
                    f"directory {name}",
                    "PASS" if path.exists() else "WARN",
                    str(path),
                )
            )
    version = migration_version(settings.database_path)
    if version is None:
        checks.append(
            Check(
                "migrations",
                "WARN" if not settings.database_path.exists() else "FAIL",
                f"database missing or unreadable: {settings.database_path}",
            )
        )
    elif version < EXPECTED_MIGRATION:
        checks.append(
            Check(
                "migrations",
                "WARN",
                f"version {version} < {EXPECTED_MIGRATION}; startup will apply pending migrations",
            )
        )
    else:
        checks.append(Check("migrations", "PASS", f"version {version}"))

    for kind in ("vision", "decision", "planner"):
        checks.append(
            Check(
                f"{kind} provider",
                "PASS" if provider_configured(settings, kind) else "FAIL",
                f"{getattr(settings, f'{kind}_provider')} (secret not printed)",
            )
        )

    if settings.api_auth_enabled:
        token = settings.api_token_path
        checks.append(
            Check(
                "api token file",
                "PASS" if token.is_file() else "WARN",
                f"{token} (generated or rotated on API start)",
            )
        )
    else:
        checks.append(Check("api auth", "WARN", "FRAME_API_AUTH_ENABLED=false"))

    if settings.feature_semantic_masks:
        registry = SemanticModelRegistry(data)
        person = registry.status("person")
        sky = registry.status("sky")
        checks.append(
            Check(
                "semantic models",
                "PASS" if person.available or sky.available else "WARN",
                f"person={person.available} sky={sky.available}",
            )
        )
    else:
        checks.append(
            Check("semantic models", "PASS", "feature disabled; no model required")
        )

    web_env = ROOT / "apps" / "web" / ".env.local"
    checks.append(
        Check(
            "web env",
            "PASS" if web_env.is_file() else "WARN",
            f"{web_env} present={web_env.is_file()}; API_INTERNAL_URL defaults to :8000",
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, help="Override FRAME_DATA_DIR for the check."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.data_dir is not None:
        settings = settings.model_copy(update={"data_dir": args.data_dir.resolve()})
    checks = run(settings)
    failed = any(check.status == "FAIL" for check in checks)
    if args.json:
        print(
            json.dumps(
                [check.__dict__ for check in checks], indent=2, ensure_ascii=False
            )
        )
    else:
        for check in checks:
            print(f"[{check.status}] {check.name}: {check.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
