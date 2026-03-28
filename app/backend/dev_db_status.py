#!/usr/bin/env python3
"""Show where the dashboard SQLite file is and what is inside (local dev helper).

Run from `app/backend/`:
  export DATA_DIR="$(cd ../.. && pwd)/var"   # recommended local path
  python dev_db_status.py

Uses the same rules as `db_store` (SQLITE_PATH, DATA_DIR, default /data).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Same directory as db_store
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db_store  # noqa: E402


def main() -> None:
    p = db_store.database_file_path()
    print("Dashboard SQLite (local / server / Cloud Run volume)")
    print("  Path: ", p.resolve())
    print("  Exists:", p.is_file())
    print()
    if not p.is_file():
        print("No database file yet.")
        print("  It is created when the Flask app first runs a query (e.g. OAuth callback or /api/data).")
        print("  For local dev, set DATA_DIR to a writable folder, e.g.:")
        print('    export DATA_DIR="$(cd ../.. && pwd)/var"')
        return

    conn = sqlite3.connect(str(p))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]
        print("Tables:", ", ".join(tables) if tables else "(none)")
        print()
        for t in tables:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} row(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
