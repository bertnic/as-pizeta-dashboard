"""Workbook DATABASE (VENDITE / ARTICOLI / TARGET)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA))

from parsers import parse_database_mart_workbook, workbook_is_database_mart_v2


def test_workbook_is_database_mart_v2(tmp_path: Path):
    p = tmp_path / "DATABASE.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        pd.DataFrame(
            {"ID": [1], "COD": ["X"], "ARTICOLO": ["P1"], "PREZZO": [9.99]}
        ).to_excel(w, sheet_name="ARTICOLI", index=False)
        pd.DataFrame(
            {
                "COD": ["X"],
                "PROV": ["BG"],
                "ANNO": [2025],
                "MESE": [1],
                "PEZZI": [5],
                "FATTURATO": [10.0],
            }
        ).to_excel(w, sheet_name="VENDITE", index=False)
        pd.DataFrame(
            {
                "COD": ["X"],
                "PROV": ["BG"],
                "ANNO": [2025],
                "MESE": [1],
                "TARGET": [7],
            }
        ).to_excel(w, sheet_name="TARGET", index=False)
    assert workbook_is_database_mart_v2(p)


def test_parse_database_mart_workbook(tmp_path: Path):
    p = tmp_path / "db.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        pd.DataFrame(
            {
                "ID": [10, 20],
                "COD": ["C1", "C2"],
                "ARTICOLO": ["Prod", "Other"],
                "PREZZO": [1.0, 2.0],
            }
        ).to_excel(w, sheet_name="ARTICOLI", index=False)
        pd.DataFrame(
            {
                "COD": ["C1", "C1"],
                "PROV": ["ONLINE", "BG"],
                "ANNO": [2025, 2025],
                "MESE": [3, 3],
                "PEZZI": [2, 4],
                "FATTURATO": [20.0, 40.0],
            }
        ).to_excel(w, sheet_name="VENDITE", index=False)
        pd.DataFrame(
            {
                "COD": ["C1"],
                "PROV": ["ONLINE"],
                "ANNO": [2025],
                "MESE": [3],
                "TARGET": [99],
            }
        ).to_excel(w, sheet_name="TARGET", index=False)

    prods, sales, tgts = parse_database_mart_workbook(p)
    assert len(prods) == 2
    assert {p["catalog_id"] for p in prods} == {"10", "20"}
    assert len(sales) == 2
    assert all(r["product_catalog_id"] == "10" for r in sales)
    assert len(tgts) == 1 and tgts[0]["pieces"] == 99 and tgts[0]["product_catalog_id"] == "10"
