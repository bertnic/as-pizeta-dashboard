"""Pivot-layout IMS sheets (e.g. ``2026`` in SEDRAN copia.xlsx)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA))

from parsers import _infer_monthly_grid_months, parse_sheet_pivot_province_product_pairs


def test_parse_pivot_two_months_bg_product():
    rows = [
        [None] * 8,
        [None] * 8,
        [None] * 8,
        [None, None, None, None, None, None, None, None],
        [None] * 8,
        [None, None, 1, None, 2, None, None, None],
        [None, "Etichette di riga", "QIMS", "Somma di FatIMS", "QIMS", "Somma di FatIMS", "QIMS  totale", "Somma di FatIMS totale"],
        [None, "SEDRAN ANNA", 100, 1000, 200, 2000, 300, 3000],
        [None, "BG", 10, 100, 20, 200, 30, 300],
        [None, "PROD-A", 5, 50, 6, 60, 11, 110],
    ]
    df = pd.DataFrame(rows)
    out = parse_sheet_pivot_province_product_pairs(df, sheet_code="2026", year=2026)
    prod = [r for r in out if r.get("product_name") == "PROD-A" and r["hierarchy_level"] == "product"]
    pieces = sorted((r["month"], r["metric"], r["value"]) for r in prod if r["metric"] == "pieces")
    rev = sorted((r["month"], r["metric"], r["value"]) for r in prod if r["metric"] == "revenue")
    assert pieces == [(1, "pieces", 5.0), (2, "pieces", 6.0)]
    assert rev == [(1, "revenue", 50.0), (2, "revenue", 60.0)]
    assert all(r["geo_code"] == "BG" for r in prod)
    assert not any(r["metric"] in ("row_total_pieces", "row_total_revenue") for r in out)


def test_infer_monthly_grid_from_width():
    assert _infer_monthly_grid_months(8, include_fat=True) == 2
    assert _infer_monthly_grid_months(24, include_fat=True) == 10
