"""Flask route: POST JSON body for product filter (avoids GET query limits / proxy quirks)."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND))


def _populate_sales(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE products (
          catalog_id TEXT NOT NULL PRIMARY KEY,
          articolo TEXT NOT NULL,
          prezzo REAL NOT NULL
        );
        INSERT INTO products (catalog_id, articolo, prezzo) VALUES
          ('1', 'P-A', 1.0),
          ('2', 'P-B', 1.0);
        CREATE TABLE sales (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_catalog_id TEXT NOT NULL REFERENCES products(catalog_id),
          year INTEGER NOT NULL,
          month INTEGER NOT NULL,
          prov TEXT,
          pieces INTEGER NOT NULL,
          value REAL NOT NULL
        );
        INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value) VALUES
          ('1', 2025, 1, 'BG', 10, 100.0),
          ('2', 2025, 1, 'BG', 1, 1000.0),
          ('2', 2025, 1, 'MI', 5, 50.0);
        """
    )
    conn.commit()


@pytest.fixture
def flask_app(monkeypatch):
    os.environ["AUTH_MODE"] = "development"
    uri = f"file:pytest_dm_{uuid.uuid4().hex}?mode=memory&cache=shared"
    master = sqlite3.connect(uri, uri=True)
    _populate_sales(master)
    import db_store

    monkeypatch.setattr(db_store, "connect", lambda: sqlite3.connect(uri, uri=True))
    monkeypatch.setattr(db_store, "ensure_initialized", lambda: None)
    sys.modules.pop("app", None)
    import app as app_module

    yield app_module.app
    master.close()


def test_get_datamart_summary_products_json_query(flask_app):
    with flask_app.test_client() as c:
        r = c.get(
            "/api/datamart/summary",
            query_string={
                "year": 2025,
                "products_json": json.dumps(["P-A"]),
            },
        )
        assert r.status_code == 200
        j = r.get_json()
        total = sum(sum(x["rev"]) for x in j["byProvince"].values())
        assert abs(total - 100.0) < 1e-6


def test_post_datamart_summary_filters_products(flask_app):
    with flask_app.test_client() as c:
        r = c.post(
            "/api/datamart/summary",
            json={"year": 2025, "products": ["P-B"]},
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200
        j = r.get_json()
        assert "BG" in j["byProvince"] and "MI" in j["byProvince"]
        assert abs(j["byProvince"]["BG"]["rev"][0] - 1000.0) < 1e-6
