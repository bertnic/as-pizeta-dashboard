"""SQLite persistence for the shared platform DB (``pizeta.sqlite``): users, mart, etc.

The database file is always ``{DATA_DIR}/pizeta.sqlite``.

If **``DATA_DIR``** is not set in the environment, it is **set in code** to ``<mono>/var``
(absolute path) when the app runs inside the mono tree. Outside mono (e.g. Docker), you must
set ``DATA_DIR`` explicitly (the image sets ``DATA_DIR=/data``).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent

_init_lock = threading.Lock()


def _mono_workspace_root() -> Path | None:
    """If this backend sits under the mono tree, return the mono root (contains ``apps/`` and ``packages/db``)."""
    for anc in _BACKEND_DIR.parents:
        if (anc / "packages" / "db" / "migrations").is_dir() and (anc / "apps").is_dir():
            return anc
    return None


def _resolved_data_dir() -> Path:
    raw = os.environ.get("DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    root = _mono_workspace_root()
    if root is None:
        raise RuntimeError(
            "DATA_DIR is not set and the dashboard backend is not inside the mono tree "
            "(expected an ancestor with packages/db/migrations and apps/). "
            "Set DATA_DIR to the directory that contains pizeta.sqlite (e.g. /data in Docker)."
        )
    var_path = (root / "var").resolve()
    os.environ["DATA_DIR"] = str(var_path)
    return var_path


_initialized = False


def reset_for_testing() -> None:
    global _initialized
    with _init_lock:
        _initialized = False


def _resolve_migration(name: str) -> Path:
    env_key = f"DASHBOARD_SCHEMA_{name.replace('.', '_').upper()}"
    if os.environ.get(env_key):
        return Path(os.environ[env_key])
    # mono/apps/dashboard/app/backend -> four parents to mono root
    mono = _BACKEND_DIR.parent.parent.parent.parent / "packages" / "db" / "migrations" / name
    if mono.is_file():
        return mono
    bundled = _BACKEND_DIR / name
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(
        f"Missing {name}. Set DASHBOARD_SCHEMA_* or keep files next to db_store.py."
    )


def _apply_app_schema(conn: sqlite3.Connection) -> None:
    for fname in (
        "001_dashboard_app.sql",
        "003_platform_new_tables.sql",
        "004_drop_dashboard_upload.sql",
    ):
        conn.executescript(_resolve_migration(fname).read_text(encoding="utf-8"))
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _ensure_datamart_schema(conn: sqlite3.Connection) -> None:
    """Create IMS mart tables (``002``) if the platform DB was created without ``migrate.py``."""
    if not _table_exists(conn, "sales"):
        conn.executescript(
            _resolve_migration("002_pharma_datamart.sql").read_text(encoding="utf-8")
        )
        conn.commit()


def database_file_path() -> Path:
    """Path to the SQLite file (no I/O): ``DATA_DIR/pizeta.sqlite`` (see ``_resolved_data_dir``)."""
    return _resolved_data_dir() / "pizeta.sqlite"


def sqlite_path() -> Path:
    p = database_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def legacy_users_path() -> Path:
    return _resolved_data_dir() / "users.json"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(sqlite_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_legacy_json(conn: sqlite3.Connection) -> None:
    """One-shot import from legacy ``users.json``; uses BEGIN IMMEDIATE so gunicorn workers do not double-migrate."""
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM users")
        user_count = cur.fetchone()["c"]

        if user_count == 0 and legacy_users_path().is_file():
            with open(legacy_users_path(), encoding="utf-8") as f:
                users = json.load(f)
            for email, u in users.items():
                cur.execute(
                    """INSERT INTO users (email, totp_secret, display_name, picture_url)
                       VALUES (?, ?, ?, ?)""",
                    (email, u["totp_secret"], u.get("name") or "", u.get("picture") or ""),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.isolation_level = ""


def ensure_initialized() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        conn = connect()
        try:
            _apply_app_schema(conn)
            _ensure_datamart_schema(conn)
            _migrate_legacy_json(conn)
        finally:
            conn.close()
        _initialized = True


def users_as_dict() -> dict:
    ensure_initialized()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT email, totp_secret, display_name, picture_url FROM users"
        )
        out = {}
        for row in cur.fetchall():
            out[row["email"]] = {
                "totp_secret": row["totp_secret"],
                "name": row["display_name"] or "",
                "picture": row["picture_url"] or "",
            }
        return out
    finally:
        conn.close()


def insert_user(email: str, totp_secret: str, name: str, picture: str) -> None:
    ensure_initialized()
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO users (email, totp_secret, display_name, picture_url)
               VALUES (?, ?, ?, ?)""",
            (email, totp_secret, name, picture),
        )
        conn.commit()
    finally:
        conn.close()


def update_user_profile(email: str, name: str, picture: str) -> None:
    """Update display name / picture for an existing user."""
    ensure_initialized()
    conn = connect()
    try:
        conn.execute(
            """UPDATE users
               SET display_name = ?, picture_url = ?
               WHERE email = ?""",
            (name, picture, email),
        )
        conn.commit()
    finally:
        conn.close()


def merge_users_from_json_file(path: Path) -> int:
    """INSERT OR IGNORE from legacy ``users.json`` (email → totp_secret, name, picture). Returns rows inserted."""
    ensure_initialized()
    if not path.is_file():
        return 0
    with open(path, encoding="utf-8") as f:
        blob = json.load(f)
    conn = connect()
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        for email, u in blob.items():
            conn.execute(
                """INSERT OR IGNORE INTO users (email, totp_secret, display_name, picture_url)
                   VALUES (?, ?, ?, ?)""",
                (email, u["totp_secret"], u.get("name") or "", u.get("picture") or ""),
            )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        return int(after - before)
    finally:
        conn.close()
