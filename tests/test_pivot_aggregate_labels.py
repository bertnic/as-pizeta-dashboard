"""Filtri etichette pivot / totali riga (last.xlsx e simili)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA))

from parsers import is_pivot_aggregate_product_name, parse_sheet_monthly_province_product


def test_is_pivot_aggregate_product_name():
    assert not is_pivot_aggregate_product_name(None)
    assert not is_pivot_aggregate_product_name("")
    assert not is_pivot_aggregate_product_name("  ")
    assert not is_pivot_aggregate_product_name("DIKIROGEN 500")
    assert is_pivot_aggregate_product_name("Totale complessivo")
    assert is_pivot_aggregate_product_name("Totale provincia")
    assert is_pivot_aggregate_product_name("Subtotale")
    assert is_pivot_aggregate_product_name("Somma di QIMS")
    assert is_pivot_aggregate_product_name("BG")


def test_monthly_sheet_skips_totals_columns_and_aggregate_rows():
    """Pezzi D.., fatturato subito dopo; colonna extra (ex totale riga) ignorata."""
    cols = 3 + 2 * 2 + 1  # 2 mesi pezzi + 2 fatt + 1 junk total
    df = pd.DataFrame([[None] * cols for _ in range(8)])
    hr = 2
    df.iat[hr, 1] = "kProvincia"
    df.iat[hr, 2] = "Articolo"
    r = hr + 1
    df.iat[r, 1] = "BG"
    df.iat[r, 2] = "P1"
    df.iat[r, 3] = 10.0
    df.iat[r, 4] = 20.0
    df.iat[r, 5] = 100.0
    df.iat[r, 6] = 200.0
    df.iat[r, 7] = 99999.0  # ex col. totale riga — non deve comparire come metrica
    r2 = hr + 2
    df.iat[r2, 1] = "BG"
    df.iat[r2, 2] = "Totale BG"
    df.iat[r2, 3] = 1.0
    df.iat[r2, 4] = 2.0
    df.iat[r2, 5] = 3.0
    df.iat[r2, 6] = 4.0

    out = parse_sheet_monthly_province_product(
        df, sheet_code="t", year=2025, max_months=2, include_fat=True
    )
    assert not any("row_total" in r["metric"] for r in out)
    assert not any(r.get("product_name") == "Totale BG" for r in out)
    p1 = [r for r in out if r.get("product_name") == "P1"]
    assert len(p1) == 4
    assert {r["metric"] for r in p1} == {"pieces", "revenue"}
    assert not any(r["value"] == 99999.0 for r in out)
