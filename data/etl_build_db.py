#!/usr/bin/env python3
"""
Crea / aggiorna il mart IMS in ``{DATA_DIR}/pizeta.sqlite`` (stesso file usato da Flask / ``db_store``).

**Sorgente (default in mono):** ``mono/datalake/DATABASE.xlsx``.
Override: ``PIZETA_DATABASE_XLSX`` o ``--xlsx``.

**DATA_DIR:** come ``db_store`` — se assente, impostato nel codice a ``mono/var`` (path assoluto); fuori mono va impostato a mano (es. ``/data``).

Fogli **VENDITE**, **ARTICOLI**, **TARGET**. Convieni ``packages/db/scripts/migrate.py`` sullo stesso DB
prima del primo run se servono anche ``users`` e tabelle platform.

Usage::

  python3 etl_build_db.py [--db path] [--xlsx path] [--append]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from parsers import parse_database_mart_workbook, workbook_is_database_mart_v2

ROOT = Path(__file__).resolve().parent


def _mono_root() -> Path | None:
    if ROOT.name != "data" or ROOT.parent.name != "dashboard":
        return None
    mono = ROOT.parent.parent.parent
    if (mono / "packages" / "db").is_dir():
        return mono
    return None


def _resolved_data_dir() -> Path:
    raw = os.environ.get("DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    m = _mono_root()
    if m is None:
        raise RuntimeError(
            "DATA_DIR is not set and etl_build_db is not running inside the mono tree. "
            "Set DATA_DIR to the directory that contains pizeta.sqlite."
        )
    var_path = (m / "var").resolve()
    os.environ["DATA_DIR"] = str(var_path)
    return var_path


def _default_workbook_path() -> Path:
    m = _mono_root()
    if m is not None:
        return m / "datalake" / "DATABASE.xlsx"
    return ROOT / "DATABASE.xlsx"


def _default_db_and_xlsx() -> tuple[Path, Path]:
    return _resolved_data_dir() / "pizeta.sqlite", _default_workbook_path()


def schema_path() -> Path:
    if env := os.environ.get("DATAMART_SCHEMA_SQL"):
        return Path(env)
    mono = ROOT.parent.parent.parent / "packages" / "db" / "migrations" / "002_pharma_datamart.sql"
    if mono.is_file():
        return mono
    return ROOT / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(schema_path().read_text(encoding="utf-8"))
    conn.commit()


def _trunc_prezzo_2dp(x: float) -> float:
    return int(float(x) * 100) / 100.0


def clear_all(conn: sqlite3.Connection) -> None:
    for tbl in ("sales", "products", "target"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.commit()


def insert_target_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO target (
          product_catalog_id, year, month, prov, pieces
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                t["product_catalog_id"],
                t["year"],
                t["month"],
                t["prov"],
                int(t["pieces"]),
            )
            for t in rows
        ],
    )
    conn.commit()
    return len(rows)


def insert_prodotti_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO products (catalog_id, articolo, prezzo)
        VALUES (?, ?, ?)
        ON CONFLICT (catalog_id) DO UPDATE SET
          articolo = excluded.articolo,
          prezzo = excluded.prezzo
        """,
        [
            (
                p["catalog_id"],
                p["articolo"],
                _trunc_prezzo_2dp(p["prezzo"]),
            )
            for p in rows
        ],
    )
    conn.commit()
    return len(rows)


def insert_sales_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO sales (
          product_catalog_id, year, month, prov, pieces, value
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["product_catalog_id"],
                r["year"],
                r["month"],
                r.get("prov"),
                int(r["pieces"]),
                float(r["value"]),
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def main() -> None:
    default_db, default_xlsx = _default_db_and_xlsx()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--db",
        type=Path,
        default=default_db,
        help="Destinazione (default: DATA_DIR/pizeta.sqlite)",
    )
    ap.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help="Workbook (default: mono/datalake/DATABASE.xlsx)",
    )
    ap.add_argument(
        "--append",
        action="store_true",
        help="Non svuotare le tabelle prima del caricamento",
    )
    args = ap.parse_args()

    xlsx = args.xlsx
    if xlsx is None:
        env_x = os.environ.get("PIZETA_DATABASE_XLSX")
        xlsx = Path(env_x).expanduser().resolve() if env_x else default_xlsx

    xlsx = xlsx.expanduser().resolve()
    if not xlsx.is_file():
        m = _mono_root()
        print(
            f"File Excel mancante: {xlsx}\n"
            f"Usa mono/datalake/DATABASE.xlsx (o imposta PIZETA_DATABASE_XLSX).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not workbook_is_database_mart_v2(xlsx):
        print(
            "Il workbook deve contenere i fogli VENDITE, ARTICOLI, TARGET.",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path = args.db.expanduser().resolve()
    conn = connect(db_path)
    apply_schema(conn)
    if not args.append:
        clear_all(conn)

    prows, srows, trows = parse_database_mart_workbook(xlsx)
    n_p = insert_prodotti_rows(conn, prows)
    n_s = insert_sales_rows(conn, srows)
    n_t = insert_target_rows(conn, trows)
    print(
        f"{xlsx.name}: products={n_p} sales={n_s} target={n_t}\n"
        f"Done. DB={db_path}"
    )
    conn.close()


if __name__ == "__main__":
    main()
