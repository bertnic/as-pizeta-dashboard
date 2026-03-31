"""Automated PHARMACIES / DB / ONLINE → sales (no manual normalization sheet required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA))

from parsers import (
    _row,
    aggregate_online_rows_to_monthly_sales,
    iter_workbook_sales_rows,
    parse_pharmacies_wide_sheet,
    parse_sheet_online,
    parse_sheet_vendite_semi,
    workbook_sales_source,
    workbook_skip_online_for_fact,
)


def test_parse_pharmacies_wide_two_months():
    # cod | name | prov | p1 p2 | v1 v2
    df = pd.DataFrame(
        [
            ["C1", "Zido", "BG", 2, 3, 20.0, 30.0],
            ["", "Header", "XX", "a", "b", "c", "d"],  # skipped (articolo header-like)
        ]
    )
    rows = parse_pharmacies_wide_sheet(df, year=2025)
    assert len(rows) == 2
    assert rows[0]["month"] == 1 and rows[0]["pieces"] == 2 and rows[0]["value"] == 20.0
    assert rows[1]["month"] == 2 and rows[1]["pieces"] == 3
    assert rows[0]["cod"] == "C1" and rows[0]["prov"] == "BG"


def test_parse_sheet_vendite_db_headers():
    df = pd.DataFrame(
        {
            "cod": ["x"],
            "name": ["Prod A"],
            "prov": ["MI"],
            "year": [2025],
            "month": [4],
            "pieces": [5],
            "value": [55.5],
        }
    )
    rows = parse_sheet_vendite_semi(df)
    assert len(rows) == 1
    assert rows[0]["articolo"] == "Prod A"
    assert rows[0]["year"] == 2025 and rows[0]["month"] == 4
    assert rows[0]["pieces"] == 5 and rows[0]["value"] == 55.5


def test_aggregate_online_monthly():
    day_rows = [
        _row(
            "ONLINE",
            "pieces",
            2.0,
            geo_code="TO",
            hierarchy_level="order_line",
            product_name="P",
            product_cod="99",
            year=2025,
            month=6,
            day=1,
        ),
        _row(
            "ONLINE",
            "revenue",
            10.0,
            geo_code="TO",
            hierarchy_level="order_line",
            product_name="P",
            product_cod="99",
            year=2025,
            month=6,
            day=2,
        ),
        _row(
            "ONLINE",
            "pieces",
            1.0,
            geo_code="TO",
            hierarchy_level="order_line",
            product_name="P",
            product_cod="99",
            year=2025,
            month=6,
            day=2,
        ),
    ]
    sales = aggregate_online_rows_to_monthly_sales(day_rows)
    assert len(sales) == 1
    assert sales[0]["pieces"] == 3.0 and sales[0]["value"] == 10.0
    assert sales[0]["year"] == 2025 and sales[0]["month"] == 6


def test_workbook_sales_pharmacies_plus_online_xlsx(tmp_path: Path):
    ph = pd.DataFrame(
        [
            ["cod", "name", "prov", 1, 1, 10.0, 10.0],
            # Avoid "C1" in Excel — spesso interpretato come data.
            ["K9", "Zido", "BG", 1, 0, 5.0, 0.0],
        ]
    )
    on = pd.DataFrame(
        [
            ["Data", "Prov", "Valore", "cod", "nome", "pezzi"],
            [pd.Timestamp("2025-01-15"), "MI", "12,5", "C2", "Other", 2],
        ]
    )
    path = tmp_path / "wb.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        ph.to_excel(w, sheet_name="PHARMACIES", header=False, index=False)
        on.to_excel(w, sheet_name="ONLINE", header=False, index=False)

    src, sales = workbook_sales_source(path)
    assert src == "pharmacies"
    assert any(r["prov"] == "BG" and r["articolo"] == "Zido" for r in sales)
    assert any(r["prov"] == "MI" and r["pieces"] == 2.0 for r in sales)
    assert workbook_skip_online_for_fact(path) is True


def test_workbook_sales_db_beats_pharmacies(tmp_path: Path):
    db = pd.DataFrame(
        {
            "cod": ["a"],
            "name": ["N"],
            "prov": ["BG"],
            "year": [2025],
            "month": [1],
            "pieces": [1],
            "value": [1.0],
        }
    )
    ph = pd.DataFrame([["C1", "Z", "BG", 5, 50.0]])
    path = tmp_path / "w2.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        db.to_excel(w, sheet_name="DB", index=False)
        ph.to_excel(w, sheet_name="PHARMACIES", header=False, index=False)

    src, sales = workbook_sales_source(path)
    assert src == "db"
    assert len(sales) == 1 and sales[0]["articolo"] == "N"


def test_parse_sheet_online_tabular_header(tmp_path: Path):
    on = pd.DataFrame(
        [
            ["Data", "Provincia", "Euro", "cod", "nome", "pezzi"],
            [pd.Timestamp("2026-01-03"), "BS", "8,00€", "1", "X", 4],
        ]
    )
    path = tmp_path / "on.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        on.to_excel(w, sheet_name="ONLINE", header=False, index=False)
    raw = pd.read_excel(path, sheet_name="ONLINE", header=None)
    rows = parse_sheet_online(raw)
    assert len(rows) >= 2
    pieces = [r for r in rows if r["metric"] == "pieces"]
    rev = [r for r in rows if r["metric"] == "revenue"]
    assert pieces[0]["value"] == 4.0
    assert rev[0]["value"] == 8.0
    assert pieces[0].get("product_cod") == "1"
