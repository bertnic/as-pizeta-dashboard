"""Tests for SQLite dashboard persistence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND))


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import db_store

    db_store.reset_for_testing()
    yield db_store
    db_store.reset_for_testing()
    p = tmp_path / "test.sqlite"
    if p.exists():
        p.unlink()


def test_users_and_uploads_roundtrip(isolated_db):
    isolated_db.ensure_initialized()
    isolated_db.insert_user("u@example.com", "TOTPSECRET", "User", "http://pic")
    users = isolated_db.users_as_dict()
    assert users["u@example.com"]["totp_secret"] == "TOTPSECRET"
    assert users["u@example.com"]["name"] == "User"

    isolated_db.append_upload("Jan report", [{"raw": "line", "values": [1.5, 2.0]}])
    payload = isolated_db.get_data_payload()
    assert len(payload["uploads"]) == 1
    assert payload["uploads"][0]["label"] == "Jan report"
    assert payload["uploads"][0]["rows"][0]["values"] == [1.5, 2.0]


def test_delete_upload_by_index(isolated_db):
    isolated_db.ensure_initialized()
    isolated_db.append_upload("a", [])
    isolated_db.append_upload("b", [])
    assert isolated_db.delete_upload_by_index(0) is True
    payload = isolated_db.get_data_payload()
    assert [u["label"] for u in payload["uploads"]] == ["b"]
    assert isolated_db.delete_upload_by_index(99) is False


def test_migrate_legacy_json(isolated_db, tmp_path):
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
    (tmp_path / "pharma_data.json").write_text(
        json.dumps({"uploads": [{"label": "L", "rows": [{"raw": "r", "values": [3]}]}]}),
        encoding="utf-8",
    )
    isolated_db.ensure_initialized()
    users = isolated_db.users_as_dict()
    assert "a@x.y" in users
    payload = isolated_db.get_data_payload()
    assert payload["uploads"][0]["label"] == "L"
