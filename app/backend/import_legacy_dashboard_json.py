#!/usr/bin/env python3
"""
Load legacy ``users.json`` into the dashboard SQLite DB (OAuth + TOTP seeds).

``db_store`` risolve il DB solo tramite ``DATA_DIR/pizeta.sqlite``. Questo script imposta
``DATA_DIR`` dalla directory del file passato a ``--db``.

Examples (from ``app/backend/``)::

  python3 import_legacy_dashboard_json.py --db /path/to/var/pizeta.sqlite --merge-users

  # users.json in un'altra cartella:
  python3 import_legacy_dashboard_json.py --db ./var/pizeta.sqlite \\
    --data-dir ~/backup/dashboard-data --merge-users
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to pizeta.sqlite (parent directory becomes DATA_DIR)",
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing users.json (default: same directory as --db)",
    )
    ap.add_argument("--users-json", type=Path, help="Override path to users.json")
    ap.add_argument(
        "--merge-users",
        action="store_true",
        help="INSERT OR IGNORE users from users.json (if file exists)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved paths and exit without writing",
    )
    args = ap.parse_args()

    db_path = args.db.expanduser().resolve()
    if db_path.name != "pizeta.sqlite":
        print(
            "Error: --db must point to a file named pizeta.sqlite "
            f"(got {db_path.name!r}).",
            file=sys.stderr,
        )
        return 1

    data_dir_for_db = db_path.parent
    os.environ["DATA_DIR"] = str(data_dir_for_db)

    users_base = (
        args.data_dir.expanduser().resolve()
        if args.data_dir
        else data_dir_for_db
    )
    users_path = (args.users_json or (users_base / "users.json")).expanduser().resolve()

    print(f"DATA_DIR:     {data_dir_for_db}")
    print(f"DB:           {db_path}")
    print(f"users.json:   {users_path}  ({'ok' if users_path.is_file() else 'missing'})")

    if args.dry_run:
        return 0

    import db_store

    db_store.reset_for_testing()
    db_store.ensure_initialized()

    nu = 0
    if args.merge_users:
        nu = db_store.merge_users_from_json_file(users_path)
        print(f"users: inserted {nu} new row(s) from users.json (existing emails unchanged)")

    if not args.merge_users:
        print(
            "Bootstrap-only: imported from users.json only if users was empty (same as first app run)."
        )

    conn = db_store.connect()
    try:
        u = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        print(f"Current counts: users={u}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
