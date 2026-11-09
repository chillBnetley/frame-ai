#!/usr/bin/env python3
"""Seed the Master Vision style library into the configured database.

Idempotent: existing profiles (including user edits and newer versions) are
skipped, never overwritten. Safe to run repeatedly and on every deployment.

Usage (from any directory):
    services/api/.venv/Scripts/python.exe scripts/seed_style_library.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

from app.core.config import Settings  # noqa: E402
from app.repositories.db import initialize_database  # noqa: E402
from app.repositories.style_repo import SqliteStyleProfileRepository  # noqa: E402
from app.styles.library import seed_style_library  # noqa: E402


def main() -> int:
    settings = Settings()
    initialize_database(settings.database_path)
    repository = SqliteStyleProfileRepository(settings.database_path)
    result = seed_style_library(repository)
    print(f"database: {settings.database_path}")
    print(f"created: {len(result.created)}, skipped: {len(result.skipped)}")
    for style_id in result.created:
        print(f"  + {style_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())