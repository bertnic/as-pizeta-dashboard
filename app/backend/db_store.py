"""SQLite persistence for dashboard users and PDF upload rows."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent

_init_lock = threading.Lock()
_initialized = False


def reset_for_testing() -> None:
    global _initialized
    with _init_lock:
        _initialized = False


def _schema_path() -> Path:
    env = os.environ.get("DASHBOARD_SCHEMA_SQL")
    if env:
        return Path(env)
    mono = _BACKEND_DIR.parent.parent.parent.parent / "packages" / "db" / "migrations" / "001_dashboard_app.sql"
    if mono.is_file():
        return mono
    bundled = _BACKEND_DIR / "001_dashboard_app.sql"
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(
        "Schema SQL not found. Set DASHBOARD_SCHEMA_SQL or add 001_dashboard_app.sql next to db_store.py."
    )


def sqlite_path() -> Path:
    if raw := os.environ.get("SQLITE_PATH"):
        p = Path(raw)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "pizeta.sqlite"


def legacy_users_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "users.json"


def legacy_data_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "pharma_data.json"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(sqlite_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    sql = _schema_path().read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def _migrate_legacy_json(conn: sqlite3.Connection) -> None:
    """One-shot import from legacy JSON; uses BEGIN IMMEDIATE so gunicorn workers do not double-migrate."""
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM dashboard_user")
        user_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM dashboard_upload")
        upload_count = cur.fetchone()["c"]

        if user_count == 0 and legacy_users_path().is_file():
            with open(legacy_users_path(), encoding="utf-8") as f:
                users = json.load(f)
            for email, u in users.items():
                cur.execute(
                    """INSERT INTO dashboard_user (email, totp_secret, display_name, picture_url)
                       VALUES (?, ?, ?, ?)""",
                    (email, u["totp_secret"], u.get("name") or "", u.get("picture") or ""),
                )
        if upload_count == 0 and legacy_data_path().is_file():
            with open(legacy_data_path(), encoding="utf-8") as f:
                blob = json.load(f)
            for u in blob.get("uploads") or []:
                cur.execute(
                    "INSERT INTO dashboard_upload (label, rows_json) VALUES (?, ?)",
                    (u["label"], json.dumps(u.get("rows") or [])),
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
            _apply_schema(conn)
            _migrate_legacy_json(conn)
        finally:
            conn.close()
        _initialized = True


def users_as_dict() -> dict:
    ensure_initialized()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT email, totp_secret, display_name, picture_url FROM dashboard_user"
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
            """INSERT INTO dashboard_user (email, totp_secret, display_name, picture_url)
               VALUES (?, ?, ?, ?)""",
            (email, totp_secret, name, picture),
        )
        conn.commit()
    finally:
        conn.close()


def get_data_payload() -> dict:
    ensure_initialized()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT label, rows_json FROM dashboard_upload ORDER BY id ASC"
        )
        uploads = []
        for row in cur.fetchall():
            uploads.append(
                {"label": row["label"], "rows": json.loads(row["rows_json"] or "[]")}
            )
        return {"uploads": uploads}
    finally:
        conn.close()


def append_upload(label: str, rows: list) -> None:
    ensure_initialized()
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO dashboard_upload (label, rows_json) VALUES (?, ?)",
            (label, json.dumps(rows)),
        )
        conn.commit()
    finally:
        conn.close()


def delete_upload_by_index(idx: int) -> bool:
    ensure_initialized()
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT id FROM dashboard_upload ORDER BY id ASC LIMIT 1 OFFSET ?",
            (idx,),
        )
        row = cur.fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM dashboard_upload WHERE id = ?", (row["id"],))
        conn.commit()
        return True
    finally:
        conn.close()
