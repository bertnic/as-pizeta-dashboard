"""Tests for SQLite dashboard persistence."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND))


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import db_store

    db_store.reset_for_testing()
    yield db_store
    db_store.reset_for_testing()
    p = tmp_path / "pizeta.sqlite"
    if p.exists():
        p.unlink()


def test_database_file_path_sets_data_dir_to_mono_var(monkeypatch):
    """Without DATA_DIR: code sets DATA_DIR to <mono>/var and opens pizeta.sqlite there."""
    monkeypatch.delenv("DATA_DIR", raising=False)
    import db_store

    p = db_store.database_file_path()
    mono_mark = p.parent.parent / "packages" / "db" / "migrations"
    if not mono_mark.is_dir():
        pytest.skip("not running from mono checkout")
    assert p.name == "pizeta.sqlite"
    assert p.parent.name == "var"
    assert (p.parent.parent / "apps").is_dir()
    assert os.environ.get("DATA_DIR") == str(p.parent.resolve())


def test_database_file_path_requires_data_dir_outside_mono(monkeypatch, tmp_path):
    """Outside mono, DATA_DIR must be set explicitly."""
    fake_backend = tmp_path / "backend"
    fake_backend.mkdir(parents=True)
    (fake_backend / "db_store.py").write_text(
        Path(BACKEND / "db_store.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.delenv("DATA_DIR", raising=False)
    sys.path.insert(0, str(fake_backend))
    try:
        spec = importlib.util.spec_from_file_location("db_store_standalone", fake_backend / "db_store.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with pytest.raises(RuntimeError, match="DATA_DIR"):
            mod.database_file_path()
    finally:
        sys.path.remove(str(fake_backend))


def test_users_roundtrip(isolated_db):
    isolated_db.ensure_initialized()
    isolated_db.insert_user("u@example.com", "TOTPSECRET", "User", "http://pic")
    users = isolated_db.users_as_dict()
    assert users["u@example.com"]["totp_secret"] == "TOTPSECRET"
    assert users["u@example.com"]["name"] == "User"


def test_merge_users_from_json_file(isolated_db, tmp_path):
    isolated_db.ensure_initialized()
    isolated_db.insert_user("existing@x.y", "OLD", "E", "")
    (tmp_path / "users.json").write_text(
        json.dumps(
            {
                "existing@x.y": {"totp_secret": "NEW", "name": "E2", "picture": ""},
                "new@x.y": {"totp_secret": "N1", "name": "N", "picture": ""},
            }
        ),
        encoding="utf-8",
    )
    n = isolated_db.merge_users_from_json_file(tmp_path / "users.json")
    assert n == 1
    users = isolated_db.users_as_dict()
    assert users["existing@x.y"]["totp_secret"] == "OLD"
    assert users["new@x.y"]["totp_secret"] == "N1"


def test_migrate_legacy_json_users_only(isolated_db, tmp_path):
    (tmp_path / "users.json").write_text(
        json.dumps(
            {
                "a@x.y": {
                    "totp_secret": "ABC123",
                    "name": "A",
                    "picture": "http://i",
                }
            }
        ),
        encoding="utf-8",
    )
    isolated_db.ensure_initialized()
    users = isolated_db.users_as_dict()
    assert "a@x.y" in users

    conn = sqlite3.connect(str(tmp_path / "pizeta.sqlite"))
    try:
        cur = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dashboard_upload'"
        )
        assert cur.fetchone() is None
    finally:
        conn.close()
