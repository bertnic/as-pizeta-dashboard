#!/usr/bin/env python3
"""
Verify datamart: rebuild logical pivots from SQLite and compare to fresh Excel/PDF parses.
Includes inverse pivots for 2025, ZIDOVAL, ONLINE, and SEDRAN (product × months 10–12).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from parsers import (
    SHEET_VENDITE_SEMI,
    iter_rows_from_xlsx,
    iter_manual_target_prezzi_fatturato,
    iter_vendite_semi_rows,
    parse_pdf_monthly,
    parse_sheet_online,
    parse_sheet_sedran_pivot,
    parse_sheet_zidoval,
    parse_sedran_def_targets_prezzi,
    read_sedran_def_sheet,
    is_sedran_def_workbook,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "pharma_datamart.sqlite"


def _has_legacy_fatt_sheet(path: Path) -> bool:
    try:
        return SHEET_VENDITE_SEMI in pd.ExcelFile(path).sheet_names
    except OSError:
        return False


def norm_key(
    sheet: str,
    geo_code: str | None,
    geo_label: str | None,
    agent_name: str | None,
    hierarchy_level: str | None,
    product_name: str | None,
    year: int | None,
    month: int | None,
    day: int | None,
    metric: str,
) -> tuple:
    return (
        sheet,
        geo_code or "",
        geo_label or "",
        agent_name or "",
        hierarchy_level or "",
        product_name or "",
        -1 if year is None else int(year),
        -1 if month is None else int(month),
        -1 if day is None else int(day),
        metric,
    )


def load_db_rows(conn: sqlite3.Connection, batch_id: int) -> dict[tuple, float]:
    cur = conn.execute(
        """
        SELECT sheet, geo_code, geo_label, agent_name, hierarchy_level, product_name,
               year, month, day, metric, value
        FROM fact_measure WHERE batch_id = ?
        """,
        (batch_id,),
    )
    out: dict[tuple, float] = {}
    for row in cur.fetchall():
        k = norm_key(*row[:10])
        out[k] = float(row[10])
    return out


def load_expected_rows(rows: list[dict]) -> dict[tuple, float]:
    out: dict[tuple, float] = {}
    for r in rows:
        k = norm_key(
            r["sheet"],
            r.get("geo_code"),
            r.get("geo_label"),
            r.get("agent_name"),
            r.get("hierarchy_level"),
            r.get("product_name"),
            r.get("year"),
            r.get("month"),
            r.get("day"),
            r["metric"],
        )
        out[k] = float(r["value"])
    return out


def compare_maps(name: str, a: dict[tuple, float], b: dict[tuple, float]) -> bool:
    keys_a = set(a)
    keys_b = set(b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    common = keys_a & keys_b
    max_diff = 0.0
    bad = 0
    for k in common:
        d = abs(a[k] - b[k])
        if d > 1e-6:
            bad += 1
            max_diff = max(max_diff, d)
    ok = not only_a and not only_b and bad == 0
    status = "OK" if ok else "MISMATCH"
    print(f"  [{status}] {name}: keys db={len(keys_a)} expected={len(keys_b)} "
          f"only_db={len(only_a)} only_expected={len(only_b)} value_mismatches={bad} max_diff={max_diff:.6g}")
    if only_a[:3]:
        print(f"    sample only_db: {only_a[:2]}")
    if only_b[:3]:
        print(f"    sample only_expected: {only_b[:2]}")
    return ok


def batch_id_for_file(conn: sqlite3.Connection, file_name: str) -> int | None:
    cur = conn.execute(
        "SELECT id FROM import_batch WHERE file_name = ? ORDER BY id DESC LIMIT 1",
        (file_name,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def pivot_2025_from_db(conn: sqlite3.Connection, batch_id: int) -> pd.DataFrame:
    """Wide pivot: rows = (province, product), columns = m{month}_{metric} for sheet 2025."""
    cur = conn.execute(
        """
        SELECT geo_code, product_name, month, metric, value
        FROM fact_measure
        WHERE batch_id = ? AND sheet = '2025' AND hierarchy_level = 'product'
          AND metric IN ('qims','fat_ims')
          AND month > 0
        ORDER BY geo_code, product_name, month, metric
        """,
        (batch_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["geo_code", "product_name", "month", "metric", "value"])
    df["col"] = "m" + df["month"].astype(str) + "_" + df["metric"]
    wide = df.pivot_table(
        index=["geo_code", "product_name"],
        columns="col",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def pivot_2025_from_excel(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="2025", header=None)
    hr = None
    for r in range(min(30, len(raw))):
        if isinstance(raw.iat[r, 1], str) and raw.iat[r, 1].strip() == "kProvincia":
            hr = r
            break
    if hr is None:
        return pd.DataFrame()
    records: list[dict] = []
    n_months = 10
    last_q = 2 + n_months
    last_f = last_q + n_months
    prov = None
    for r in range(hr + 1, len(raw)):
        p = raw.iat[r, 1]
        art = raw.iat[r, 2]
        if isinstance(p, str) and p.strip():
            prov = p.strip()
        if not prov or pd.isna(art):
            continue
        prod = str(art).strip()
        for mi in range(n_months):
            qv = raw.iat[r, 3 + mi]
            fv = raw.iat[r, last_q + mi]
            if pd.notna(qv) and isinstance(qv, (int, float)):
                records.append(
                    {"geo_code": prov, "product_name": prod, "month": mi + 1, "metric": "qims", "value": float(qv)}
                )
            if pd.notna(fv) and isinstance(fv, (int, float)):
                records.append(
                    {"geo_code": prov, "product_name": prod, "month": mi + 1, "metric": "fat_ims", "value": float(fv)}
                )
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["col"] = "m" + df["month"].astype(str) + "_" + df["metric"]
    wide = df.pivot_table(
        index=["geo_code", "product_name"],
        columns="col",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def compare_pivot_frames(a: pd.DataFrame, b: pd.DataFrame, label: str) -> bool:
    if a.empty and b.empty:
        print(f"  [SKIP] {label}: empty")
        return True
    if a.empty != b.empty:
        print(f"  [MISMATCH] {label}: one side empty (db={not a.empty} xl={not b.empty})")
        return False
    a2, b2 = a.align(b, join="outer")
    diff = (a2.fillna(0.0) - b2.fillna(0.0)).abs()
    mx = float(diff.to_numpy().max()) if diff.size else 0.0
    ncells = diff.size
    nbad = int((diff > 1e-6).sum().sum()) if diff.size else 0
    ok = nbad == 0
    print(f"  [{'OK' if ok else 'MISMATCH'}] {label}: cells={ncells} max_abs_diff={mx:.6g} bad_cells={nbad}")
    return ok


def pivot_zidoval_from_db(conn: sqlite3.Connection, batch_id: int) -> pd.DataFrame:
    cur = conn.execute(
        """
        SELECT geo_label, year, month, value
        FROM fact_measure
        WHERE batch_id = ? AND sheet = 'ZIDOVAL 2025' AND metric = 'zidoval_units'
        ORDER BY geo_label, year, month
        """,
        (batch_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["geo_label", "year", "month", "value"])
    df["col"] = df["year"].astype(str) + "_" + df["month"].astype(str)
    wide = df.pivot_table(index=["geo_label"], columns="col", values="value", aggfunc="sum")
    return wide.sort_index()


def pivot_zidoval_from_excel(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="ZIDOVAL 2025", header=None)
    rows = parse_sheet_zidoval(raw)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [{"geo_label": r["geo_label"], "year": r["year"], "month": r["month"], "value": r["value"]} for r in rows]
    )
    df["col"] = df["year"].astype(str) + "_" + df["month"].astype(str)
    wide = df.pivot_table(index=["geo_label"], columns="col", values="value", aggfunc="sum")
    return wide.sort_index()


def pivot_online_from_db(conn: sqlite3.Connection, batch_id: int) -> pd.DataFrame:
    cur = conn.execute(
        """
        SELECT year, month, day, geo_code, product_name, metric, value
        FROM fact_measure
        WHERE batch_id = ? AND sheet = 'ONLINE' AND metric IN ('quantity','net')
        ORDER BY year, month, day, geo_code, product_name, metric
        """,
        (batch_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows, columns=["year", "month", "day", "geo_code", "product_name", "metric", "value"]
    )
    wide = df.pivot_table(
        index=["year", "month", "day", "geo_code", "product_name"],
        columns="metric",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def pivot_online_from_excel(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="ONLINE", header=None)
    rows = parse_sheet_online(raw)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [
            {
                "year": r["year"],
                "month": r["month"],
                "day": r["day"],
                "geo_code": r.get("geo_code"),
                "product_name": r.get("product_name"),
                "metric": r["metric"],
                "value": r["value"],
            }
            for r in rows
        ]
    )
    wide = df.pivot_table(
        index=["year", "month", "day", "geo_code", "product_name"],
        columns="metric",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def pivot_sedran_products_from_db(conn: sqlite3.Connection, batch_id: int) -> pd.DataFrame:
    cur = conn.execute(
        """
        SELECT geo_code, product_name, month, metric, value
        FROM fact_measure
        WHERE batch_id = ? AND sheet = 'SEDRAN' AND hierarchy_level = 'product'
          AND metric IN ('qims','fat_ims') AND month IN (10, 11, 12)
        ORDER BY geo_code, product_name, month, metric
        """,
        (batch_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["geo_code", "product_name", "month", "metric", "value"])
    df["col"] = "m" + df["month"].astype(str) + "_" + df["metric"]
    wide = df.pivot_table(
        index=["geo_code", "product_name"],
        columns="col",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def pivot_sedran_products_from_excel(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name="SEDRAN", header=None)
    if raw.shape[1] < 9:
        return pd.DataFrame()
    if (
        raw.shape[0] > 6
        and isinstance(raw.iat[6, 1], str)
        and str(raw.iat[6, 1]).strip() == "kProvincia"
        and raw.shape[1] >= 15
    ):
        return pd.DataFrame()
    rows = parse_sheet_sedran_pivot(raw, year=2025)
    recs = [
        {
            "geo_code": r["geo_code"],
            "product_name": r["product_name"],
            "month": r["month"],
            "metric": r["metric"],
            "value": r["value"],
        }
        for r in rows
        if r.get("hierarchy_level") == "product"
        and r["metric"] in ("qims", "fat_ims")
        and r.get("month") in (10, 11, 12)
    ]
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    df["col"] = "m" + df["month"].astype(str) + "_" + df["metric"]
    wide = df.pivot_table(
        index=["geo_code", "product_name"],
        columns="col",
        values="value",
        aggfunc="sum",
    )
    return wide.sort_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db} — run etl_build_db.py first")

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row

    print("=== Key-level equality (DB vs fresh parse) ===")
    all_ok = True
    for path in sorted(ROOT.glob("*.xlsx")):
        bid = batch_id_for_file(conn, path.name)
        if bid is None:
            continue
        expected = load_expected_rows(list(iter_rows_from_xlsx(path)))
        actual = load_db_rows(conn, bid)
        if not compare_maps(path.name, actual, expected):
            all_ok = False

        tg_man, pr_man, ft_man = iter_manual_target_prezzi_fatturato(path)
        tg_def: list = []
        pr_def: list = []
        if is_sedran_def_workbook(path):
            df = read_sedran_def_sheet(path)
            if df is not None:
                tg_def, pr_def = parse_sedran_def_targets_prezzi(df)

        exp_t = len(tg_def) + len(tg_man)
        exp_p = len({p["articolo"] for p in (pr_def + pr_man)})
        exp_f = len(ft_man) + (
            len(iter_vendite_semi_rows(path)) if _has_legacy_fatt_sheet(path) else 0
        )

        n_t = conn.execute("SELECT COUNT(*) FROM TARGET WHERE batch_id = ?", (bid,)).fetchone()[0]
        n_p = conn.execute("SELECT COUNT(*) FROM PRODOTTI WHERE batch_id = ?", (bid,)).fetchone()[0]
        n_f = conn.execute("SELECT COUNT(*) FROM FATTURATO WHERE batch_id = ?", (bid,)).fetchone()[0]

        if exp_t or exp_p or exp_f:
            t_ok = n_t == exp_t
            p_ok = n_p == exp_p
            f_ok = n_f == exp_f
            ok = t_ok and p_ok and f_ok
            print(
                f"  [{'OK' if ok else 'MISMATCH'}] {path.name} TARGET/PRODOTTI/FATTURATO: "
                f"db T={n_t} exp={exp_t}, db P={n_p} exp={exp_p}, db F={n_f} exp={exp_f}"
            )
            if not ok:
                all_ok = False

    for path in sorted(ROOT.glob("*.pdf")):
        bid = batch_id_for_file(conn, path.name)
        if bid is None:
            continue
        expected = load_expected_rows(parse_pdf_monthly(path))
        actual = load_db_rows(conn, bid)
        if not compare_maps(path.name, actual, expected):
            all_ok = False

    print("\n=== Inverse pivot checks (DB wide ↔ Excel) ===")
    pivot_ok = True
    for path in sorted(ROOT.glob("*.xlsx")):
        bid = batch_id_for_file(conn, path.name)
        if bid is None:
            continue
        xl = pd.ExcelFile(path)
        sn = xl.sheet_names
        prefix = path.name

        if "2025" in sn:
            if not compare_pivot_frames(
                pivot_2025_from_db(conn, bid),
                pivot_2025_from_excel(path),
                f"{prefix} | sheet 2025",
            ):
                pivot_ok = False

        if "ZIDOVAL 2025" in sn:
            if not compare_pivot_frames(
                pivot_zidoval_from_db(conn, bid),
                pivot_zidoval_from_excel(path),
                f"{prefix} | ZIDOVAL 2025",
            ):
                pivot_ok = False

        if "ONLINE" in sn:
            if not compare_pivot_frames(
                pivot_online_from_db(conn, bid),
                pivot_online_from_excel(path),
                f"{prefix} | ONLINE",
            ):
                pivot_ok = False

        if "SEDRAN" in sn:
            raw = pd.read_excel(path, sheet_name="SEDRAN", header=None)
            is_def_layout = raw.shape[1] >= 15 and isinstance(raw.iat[6, 1], str) and str(raw.iat[6, 1]).strip() == "kProvincia"
            if not is_def_layout and raw.shape[1] >= 9:
                if not compare_pivot_frames(
                    pivot_sedran_products_from_db(conn, bid),
                    pivot_sedran_products_from_excel(path),
                    f"{prefix} | SEDRAN (prod m10–12)",
                ):
                    pivot_ok = False

    if pivot_ok:
        sample = "SEDRAN (1).xlsx"
        bid = batch_id_for_file(conn, sample)
        if bid is not None:
            p_db = pivot_2025_from_db(conn, bid)
            if not p_db.empty:
                print("\nSample pivot head (2025 from {}):".format(sample))
                with pd.option_context("display.width", 120, "display.max_columns", 8):
                    print(p_db.iloc[:3, :6].to_string())

    all_ok = all_ok and pivot_ok

    conn.close()
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
