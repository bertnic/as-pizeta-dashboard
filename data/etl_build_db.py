#!/usr/bin/env python3
"""
Create / refresh SQLite datamart and load Excel + PDF from this directory.

Default: workbook canonici (SEDRAN (1).xlsx, SEDRAN DEF..xlsx) + PDF.
SEDRAN DEF → tabelle TARGET + PRODOTTI (cod opzionale).

Foglio manuale ``1TQAGiWBTbYf9IPUqrhS9DBv5WFftDPqI`` (se presente in un .xlsx caricato):
  blocchi TARGET / PREZZI|PRODOTTI / FATTURATO → tabelle TARGET, PRODOTTI, FATTURATO.

Usage:
  python3 etl_build_db.py [--db path] [--all-xlsx] [--append]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from parsers import (
    CANONICAL_XLSX_NAMES,
    iter_rows_from_xlsx,
    iter_manual_target_prezzi_fatturato,
    iter_vendite_semi_rows,
    parse_pdf_monthly,
    parse_sedran_def_targets_prezzi,
    read_sedran_def_sheet,
    is_sedran_def_workbook,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "pharma_datamart.sqlite"


def schema_path() -> Path:
    """DDL for the datamart (not the Flask app DB)."""
    if env := os.environ.get("DATAMART_SCHEMA_SQL"):
        return Path(env)
    mono = ROOT.parent.parent.parent / "packages" / "db" / "migrations" / "002_pharma_datamart.sql"
    if mono.is_file():
        return mono
    return ROOT / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(schema_path().read_text(encoding="utf-8"))
    conn.commit()


def clear_all(conn: sqlite3.Connection) -> None:
    for tbl in ("FATTURATO", "PRODOTTI", "TARGET", "fact_measure", "import_batch"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()


def insert_batch(conn: sqlite3.Connection, source_path: Path, source_kind: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO import_batch (source_path, file_name, source_kind, loaded_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            str(source_path.resolve()),
            source_path.name,
            source_kind,
            datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_fact_rows(conn: sqlite3.Connection, batch_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO fact_measure (
          batch_id, sheet, geo_code, geo_label, agent_name, hierarchy_level,
          product_name, year, month, day, metric, value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                batch_id,
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
                r["value"],
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def insert_target_rows(conn: sqlite3.Connection, batch_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO TARGET (batch_id, cod, articolo, anno, mese, prov, qta)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                batch_id,
                t.get("cod"),
                t["articolo"],
                t["anno"],
                t["mese"],
                t["prov"],
                t["qta"],
            )
            for t in rows
        ],
    )
    conn.commit()
    return len(rows)


def insert_prodotti_rows(conn: sqlite3.Connection, batch_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO PRODOTTI (batch_id, cod, articolo, prezzo)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (batch_id, articolo) DO UPDATE SET
          prezzo = excluded.prezzo,
          cod = COALESCE(excluded.cod, PRODOTTI.cod)
        """,
        [(batch_id, p.get("cod"), p["articolo"], p["prezzo"]) for p in rows],
    )
    conn.commit()
    return len(rows)


def insert_fatturato_rows(conn: sqlite3.Connection, batch_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO FATTURATO (batch_id, cod, articolo, anno, mese, prov, qta, valore)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                batch_id,
                r.get("cod"),
                r["articolo"],
                r["anno"],
                r["mese"],
                r.get("prov"),
                r["qta"],
                r["valore"],
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--all-xlsx",
        action="store_true",
        help="Importa tutti i file .xlsx nella cartella (non solo i canonici)",
    )
    ap.add_argument("--append", action="store_true", help="Non svuotare le tabelle prima del caricamento")
    args = ap.parse_args()

    conn = connect(args.db)
    apply_schema(conn)
    if not args.append:
        clear_all(conn)

    xlsx_files = sorted(ROOT.glob("*.xlsx"))
    if not args.all_xlsx:
        xlsx_files = [f for f in xlsx_files if f.name in CANONICAL_XLSX_NAMES]
        missing = CANONICAL_XLSX_NAMES - {f.name for f in xlsx_files}
        for m in sorted(missing):
            print(f"Warning: file canonico mancante: {m}")

    total_facts = 0
    total_target = 0
    total_prodotti = 0
    total_fatturato = 0

    for xlsx in xlsx_files:
        bid = insert_batch(conn, xlsx, "xlsx")

        if is_sedran_def_workbook(xlsx):
            df = read_sedran_def_sheet(xlsx)
            if df is not None:
                tg, pr = parse_sedran_def_targets_prezzi(df)
                total_target += insert_target_rows(conn, bid, tg)
                total_prodotti += insert_prodotti_rows(conn, bid, pr)
                print(
                    f"{xlsx.name}: batch {bid}, DEF → TARGET={len(tg)} PRODOTTI={len(pr)}"
                )

        tg_m, pr_m, ft_m = iter_manual_target_prezzi_fatturato(xlsx)
        if tg_m or pr_m or ft_m:
            total_target += insert_target_rows(conn, bid, tg_m)
            total_prodotti += insert_prodotti_rows(conn, bid, pr_m)
            total_fatturato += insert_fatturato_rows(conn, bid, ft_m)
            print(
                f"{xlsx.name}: batch {bid}, foglio manuale 1TQAG… → "
                f"TARGET+{len(tg_m)} PRODOTTI+{len(pr_m)} FATTURATO+{len(ft_m)}"
            )

        rows = list(iter_rows_from_xlsx(xlsx))
        nf = insert_fact_rows(conn, bid, rows)
        total_facts += nf
        print(f"{xlsx.name}: batch {bid}, fact_measure={nf}")

        nv = insert_fatturato_rows(conn, bid, iter_vendite_semi_rows(xlsx))
        total_fatturato += nv
        if nv:
            print(f"{xlsx.name}: foglio legacy 1W7R3… → FATTURATO+{nv}")

    for pdf in sorted(ROOT.glob("*.pdf")):
        rows = parse_pdf_monthly(pdf)
        bid = insert_batch(conn, pdf, "pdf")
        nf = insert_fact_rows(conn, bid, rows)
        total_facts += nf
        print(f"{pdf.name}: batch {bid}, {nf} measures")

    print(
        f"Done. DB={args.db} fact_measure={total_facts} "
        f"TARGET={total_target} PRODOTTI_rows={total_prodotti} FATTURATO={total_fatturato}"
    )
    conn.close()


if __name__ == "__main__":
    main()
