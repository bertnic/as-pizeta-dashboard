"""Tests for datamart_summary aggregation (sales + target only)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from datamart_summary import (
    build_dashboard_api_payload,
    build_dashboard_dataset,
    build_sales_dashboard_dataset,
    list_datamart_years,
)


def _sales_ddl() -> str:
    return """
        CREATE TABLE products (
          catalog_id TEXT NOT NULL PRIMARY KEY,
          articolo TEXT NOT NULL,
          prezzo REAL NOT NULL
        );
        CREATE TABLE sales (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_catalog_id TEXT NOT NULL REFERENCES products(catalog_id),
          year INTEGER NOT NULL,
          month INTEGER NOT NULL,
          prov TEXT,
          pieces INTEGER NOT NULL,
          value REAL NOT NULL
        );
        """


def test_build_sales_dashboard_dataset_empty():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    try:
        assert build_sales_dashboard_dataset(conn) is None
    finally:
        conn.close()


def test_build_sales_dashboard_dataset_aggregates():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.executemany(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES (?, ?, ?)",
        [("1", "P1", 1.0), ("2", "P2", 1.0)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            ("1", 2024, 1, "BG", 2, 20.0),
            ("1", 2024, 1, "BG", 3, 30.0),
            ("2", 2024, 1, "BS", 1, 10.0),
        ],
    )
    conn.commit()
    try:
        d = build_sales_dashboard_dataset(conn, year=2024)
        assert d is not None
        assert d["year"] == 2024
        assert "BG" in d["byProvince"] and "BS" in d["byProvince"]
        assert d["byProvince"]["BG"]["qty"][0] == 5
        assert d["byProvince"]["BG"]["rev"][0] == 50.0
        assert len(d["topProducts"]) >= 1
        assert len(d["productsCatalog"]) == 2
    finally:
        conn.close()


def test_build_sales_dashboard_dataset_product_filter():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.executemany(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES (?, ?, ?)",
        [("10", "P1", 1.0), ("11", "P2", 1.0)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            ("10", 2024, 1, "BG", 10, 100.0),
            ("11", 2024, 1, "BG", 1, 1000.0),
            ("11", 2024, 1, "BS", 2, 20.0),
        ],
    )
    conn.commit()
    try:
        d_all = build_sales_dashboard_dataset(conn, year=2024)
        assert d_all["byProvince"]["BG"]["qty"][0] == 11
        d_a = build_sales_dashboard_dataset(conn, year=2024, product_filter=frozenset({"P1"}))
        assert d_a is not None
        assert d_a["byProvince"]["BG"]["qty"][0] == 10
        assert "BS" not in d_a["byProvince"]
        assert len(d_a["productsCatalog"]) == 2
    finally:
        conn.close()


def test_build_dashboard_dataset_prefers_sales():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('1', 'X', 1)"
    )
    conn.execute(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('1', 2024, 1, 'MI', 1, 10)"""
    )
    conn.commit()
    try:
        d = build_dashboard_dataset(conn)
        assert d is not None
        assert "fatturato" in d["label"].lower()
        assert d["year"] == 2024
    finally:
        conn.close()


def _mart_ddl_with_target() -> str:
    return _sales_ddl() + """
        CREATE TABLE target (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          product_catalog_id TEXT NOT NULL REFERENCES products(catalog_id),
          year INTEGER NOT NULL,
          month INTEGER NOT NULL,
          prov TEXT NOT NULL,
          pieces INTEGER NOT NULL
        );
        """


def test_build_dashboard_api_payload_prior_and_target():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_mart_ddl_with_target())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('5', 'P', 1)"
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('5', ?, 1, 'BG', ?, ?)""",
        [(2024, 10, 100.0), (2025, 20, 200.0)],
    )
    conn.execute(
        """INSERT INTO target (product_catalog_id, year, month, prov, pieces)
           VALUES ('5', 2025, 1, 'BG', 100)"""
    )
    conn.commit()
    try:
        d = build_dashboard_api_payload(conn, year=2025)
        assert d is not None
        assert 2025 in d["availableYears"] and 2024 in d["availableYears"]
        assert d["priorYear"] is not None
        assert d["priorYear"]["year"] == 2024
        assert d["priorYear"]["byProvince"]["BG"]["qty"][0] == 10.0
        assert d["target"] is not None
        assert d["target"]["byProvince"]["BG"]["qty"][0] == 100.0
        assert d["productsCatalog"] and d["productsCatalog"][0]["name"] == "P"
    finally:
        conn.close()


def test_build_dashboard_api_payload_product_filter_prior_year():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.executemany(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES (?, ?, ?)",
        [("1", "OnlyP", 1.0), ("2", "Other", 1.0)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, ?, 1, 'BG', ?, ?)""",
        [
            ("1", 2024, 1, 10.0),
            ("1", 2025, 2, 20.0),
            ("2", 2025, 100, 1000.0),
        ],
    )
    conn.commit()
    try:
        d = build_dashboard_api_payload(conn, year=2025, product_filter=frozenset({"OnlyP"}))
        assert d is not None
        assert d["priorYear"] is not None
        assert d["priorYear"]["byProvince"]["BG"]["qty"][0] == 1.0
        assert d["byProvince"]["BG"]["qty"][0] == 2.0
    finally:
        conn.close()


def test_build_dashboard_api_payload_target_respects_product_filter():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_mart_ddl_with_target())
    conn.executemany(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES (?, ?, ?)",
        [("1", "A", 1.0), ("2", "B", 1.0)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, 2025, 1, 'BG', 1, 1)""",
        [("1",), ("2",)],
    )
    conn.executemany(
        """INSERT INTO target (product_catalog_id, year, month, prov, pieces)
           VALUES (?, 2025, 1, 'BG', ?)""",
        [("1", 50), ("2", 150)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, 2024, 1, 'BG', 1, 1)""",
        [("1",), ("2",)],
    )
    conn.commit()
    try:
        d_all = build_dashboard_api_payload(conn, year=2025)
        assert d_all["target"]["byProvince"]["BG"]["qty"][0] == 200.0
        d_a = build_dashboard_api_payload(conn, year=2025, product_filter=frozenset({"A"}))
        assert d_a["target"]["byProvince"]["BG"]["qty"][0] == 50.0
    finally:
        conn.close()


def test_build_dashboard_api_payload_includes_products_series_with_target():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_mart_ddl_with_target())
    conn.executemany(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES (?, ?, ?)",
        [("1", "A", 1.0), ("2", "B", 1.0)],
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES (?, 2025, ?, ?, ?, ?)""",
        [("1", 1, "BG", 10, 100.0), ("2", 1, "BG", 5, 50.0)],
    )
    conn.executemany(
        """INSERT INTO target (product_catalog_id, year, month, prov, pieces)
           VALUES (?, 2025, 1, 'BG', ?)""",
        [("1", 12), ("2", 7)],
    )
    conn.commit()
    try:
        d = build_dashboard_api_payload(conn, year=2025)
        assert d is not None
        rows = d.get("productsSeries") or []
        assert len(rows) == 2
        by_name = {r["name"]: r for r in rows}
        assert by_name["A"]["qty"] == 10.0 and by_name["A"]["targetQty"] == 12.0
        assert by_name["B"]["qty"] == 5.0 and by_name["B"]["targetQty"] == 7.0
    finally:
        conn.close()


def test_build_dashboard_api_payload_ignores_year_not_in_database():
    """Evita payload null se ?year= punta a un anno senza righe in sales."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('1', 'P', 1)"
    )
    conn.execute(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('1', 2025, 1, 'BG', 1, 10)"""
    )
    conn.commit()
    try:
        assert list_datamart_years(conn) == [2025]
        d = build_dashboard_api_payload(conn, year=1999)
        assert d is not None
        assert d["year"] == 2025
    finally:
        conn.close()


def test_build_sales_dashboard_includes_sales_without_matching_product_row():
    """LEFT JOIN: righe ``sales`` con ``product_catalog_id`` orfano restano nei totali provincia×mese."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(_sales_ddl())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('1', 'OK', 1)"
    )
    conn.execute(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('orphan', 2024, 2, 'BG', 7, 70.0)"""
    )
    conn.commit()
    try:
        d = build_sales_dashboard_dataset(conn, year=2024)
        assert d is not None
        assert d["byProvince"]["BG"]["qty"][1] == 7.0
    finally:
        conn.close()


def test_build_dashboard_api_payload_returns_none_when_all_months_invalid():
    """Se tutti i month sono fuori 1..12, il payload finale è null (UI: Nessun dataset)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('1', 'P', 1)"
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('1', 2025, ?, 'BG', 1, 10)""",
        [(0,), (13,)],
    )
    conn.commit()
    try:
        # L'anno esiste comunque in tabella, ma l'aggregazione scarta i month invalidi.
        assert list_datamart_years(conn) == [2025]
        assert build_dashboard_api_payload(conn, year=2025) is None
    finally:
        conn.close()


def test_build_dashboard_api_payload_not_none_when_at_least_one_month_valid():
    """Basta una riga con month valido per avere payload chart-ready lato API."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_sales_ddl())
    conn.execute(
        "INSERT INTO products (catalog_id, articolo, prezzo) VALUES ('1', 'P', 1)"
    )
    conn.executemany(
        """INSERT INTO sales (product_catalog_id, year, month, prov, pieces, value)
           VALUES ('1', 2025, ?, 'BG', 1, 10)""",
        [(0,), (1,), (13,)],
    )
    conn.commit()
    try:
        d = build_dashboard_api_payload(conn, year=2025)
        assert d is not None
        assert d["byProvince"]["BG"]["qty"][0] == 1.0
    finally:
        conn.close()
