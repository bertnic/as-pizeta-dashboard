"""
Build dashboard-shaped JSON from IMS mart data.

``sales`` / ``target`` link to ``products`` via ``product_catalog_id → products.catalog_id``.
Product names for filters and catalog come from ``products.articolo``.
Time columns: ``year``, ``month`` (calendar).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def list_datamart_years(conn: sqlite3.Connection) -> list[int]:
    """Distinct calendar years with **actuals** in ``sales``, not target-only."""
    years: set[int] = set()
    if not _table_exists(conn, "sales"):
        return []
    for (y,) in conn.execute(
        "SELECT DISTINCT year FROM sales WHERE year IS NOT NULL"
    ):
        years.add(int(y))
    return sorted(years, reverse=True)


def build_target_pieces_rollup(
    conn: sqlite3.Connection,
    year: int,
    product_filter: frozenset[str] | None = None,
) -> dict | None:
    """Province × month target pieces (no revenue in ``target`` table).

    When ``product_filter`` is non-empty, only rows whose ``products.articolo`` matches
    (trimmed, same strings as the UI picker) are summed.
    """
    if not _table_exists(conn, "target"):
        return None
    pf_sql, pf_args = _sql_in_clause(
        "p.articolo", product_filter, trim_column=bool(product_filter)
    )
    join = (
        "INNER JOIN products p ON t.product_catalog_id = p.catalog_id"
        if product_filter
        else "LEFT JOIN products p ON t.product_catalog_id = p.catalog_id"
    )
    ex_art = (
        _sql_exclude_pseudo_product("p.articolo")
        if product_filter
        else _sql_exclude_pseudo_product_allow_orphan("p.articolo")
    )
    cur = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM target t
        {join}
        WHERE t.year = ?{pf_sql}{ex_art}
        """,
        (year,) + pf_args,
    )
    if cur.fetchone()[0] == 0:
        return None
    cur = conn.execute(
        f"""
        SELECT t.prov, t.month, SUM(t.pieces)
        FROM target t
        {join}
        WHERE t.year = ?{pf_sql}{ex_art}
        GROUP BY t.prov, t.month
        """,
        (year,) + pf_args,
    )
    byp: dict[str, dict] = defaultdict(lambda: {"qty": [0] * 12, "rev": [0.0] * 12})
    provs: set[str] = set()
    for prov, month, pieces in cur.fetchall():
        if month is None or not (1 <= int(month) <= 12):
            continue
        p = (str(prov).strip().upper() if prov is not None else "") or "—"
        provs.add(p)
        mi = int(month) - 1
        byp[p]["qty"][mi] += float(pieces or 0)
    if not provs:
        return None
    prov_sorted = sorted(provs)
    return {
        "year": year,
        "months": _MONTHS_IT,
        "provinces": prov_sorted,
        "byProvince": {p: byp[p] for p in prov_sorted},
    }


def build_dashboard_api_payload(
    conn: sqlite3.Connection,
    year: int | None = None,
    product_filter: frozenset[str] | None = None,
) -> dict | None:
    """
    Dashboard JSON: main mart slice for ``year`` (default = newest year with data),
    optional ``priorYear`` (calendar year − 1) and ``target`` (pieces targets for ``year``).

    ``product_filter``: when non-empty, restrict rollups, ``topProducts``, and **target**
    to those ``products.articolo`` names. ``productsCatalog`` is always the full-year list for the UI picker.
    """
    years = list_datamart_years(conn)
    if not years:
        return None
    year_set = set(years)
    y = year if year is not None and year in year_set else years[0]
    main = build_dashboard_dataset(conn, y, product_filter=product_filter)
    if main is None:
        for try_y in years:
            main = build_dashboard_dataset(conn, try_y, product_filter=product_filter)
            if main is not None:
                y = try_y
                break
    if main is None:
        return None

    py = y - 1
    prior_data = build_dashboard_dataset(conn, py, product_filter=product_filter)
    prior_block = None
    if prior_data:
        prior_block = {
            "year": py,
            "months": prior_data["months"],
            "byProvince": prior_data["byProvince"],
        }

    tgt = build_target_pieces_rollup(conn, y, product_filter=product_filter)
    target_block = tgt

    return {
        **main,
        "availableYears": years,
        "priorYear": prior_block,
        "target": target_block,
    }


_MONTHS_IT = [
    "Gen",
    "Feb",
    "Mar",
    "Apr",
    "Mag",
    "Giu",
    "Lug",
    "Ago",
    "Set",
    "Ott",
    "Nov",
    "Dic",
]

_EXCLUDE_PSEUDO_PRODUCT_NAMES_LOWER: tuple[str, ...] = (
    "totale complessivo",
)


def _sql_exclude_pseudo_product(column: str) -> str:
    if not _EXCLUDE_PSEUDO_PRODUCT_NAMES_LOWER:
        return ""
    listed = ", ".join(f"'{n}'" for n in _EXCLUDE_PSEUDO_PRODUCT_NAMES_LOWER)
    return f" AND LOWER(TRIM(COALESCE({column}, ''))) NOT IN ({listed})"


def _sql_exclude_pseudo_product_allow_orphan(column: str) -> str:
    """Like ``_sql_exclude_pseudo_product`` but keep rows with no matching ``products`` row."""
    if not _EXCLUDE_PSEUDO_PRODUCT_NAMES_LOWER:
        return ""
    listed = ", ".join(f"'{n}'" for n in _EXCLUDE_PSEUDO_PRODUCT_NAMES_LOWER)
    inner = f"LOWER(TRIM(COALESCE({column}, ''))) NOT IN ({listed})"
    return f" AND (p.catalog_id IS NULL OR ({inner}))"


def _sql_in_clause(
    column: str, values: frozenset[str] | None, *, trim_column: bool = False
) -> tuple[str, tuple]:
    if not values:
        return "", ()
    col_expr = f"TRIM({column})" if trim_column else column
    placeholders = ", ".join("?" * len(values))
    return f" AND {col_expr} IN ({placeholders})", tuple(values)


def build_sales_dashboard_dataset(
    conn: sqlite3.Connection,
    year: int | None = None,
    product_filter: frozenset[str] | None = None,
) -> dict | None:
    """
    Aggregate ``sales`` by province × month for the latest year (or ``year``),
    joining ``products`` for product name filters and catalog.
    """
    cur = conn.execute("SELECT COUNT(*) FROM sales")
    if cur.fetchone()[0] == 0:
        return None

    y = year
    if y is None:
        row = conn.execute("SELECT MAX(year) FROM sales WHERE year IS NOT NULL").fetchone()
        if not row or row[0] is None:
            return None
        y = int(row[0])

    pf_sql, pf_args = _sql_in_clause(
        "p.articolo", product_filter, trim_column=bool(product_filter)
    )
    join = (
        "INNER JOIN products p ON s.product_catalog_id = p.catalog_id"
        if product_filter
        else "LEFT JOIN products p ON s.product_catalog_id = p.catalog_id"
    )
    ex_art = (
        _sql_exclude_pseudo_product("p.articolo")
        if product_filter
        else _sql_exclude_pseudo_product_allow_orphan("p.articolo")
    )
    cur = conn.execute(
        f"""
        SELECT s.prov, s.month, SUM(s.pieces), SUM(s.value)
        FROM sales s
        {join}
        WHERE s.year = ?{pf_sql}{ex_art}
        GROUP BY s.prov, s.month
        """,
        (y,) + pf_args,
    )
    byp: dict[str, dict] = defaultdict(lambda: {"qty": [0] * 12, "rev": [0.0] * 12})
    provs: set[str] = set()
    for prov, month, qta, valore in cur.fetchall():
        if month is None or not (1 <= int(month) <= 12):
            continue
        p = (str(prov).strip().upper() if prov is not None else "") or "—"
        provs.add(p)
        mi = int(month) - 1
        byp[p]["qty"][mi] += float(qta or 0)
        byp[p]["rev"][mi] += float(valore or 0)

    if not provs:
        if not product_filter:
            return None
        catalog_rows = conn.execute(
            f"""
            SELECT p.articolo, SUM(s.pieces), SUM(s.value)
            FROM sales s
            INNER JOIN products p ON s.product_catalog_id = p.catalog_id
            WHERE s.year = ? AND p.articolo IS NOT NULL AND TRIM(p.articolo) != ''
            {_sql_exclude_pseudo_product("p.articolo")}
            GROUP BY p.articolo
            ORDER BY SUM(s.value) DESC
            """,
            (y,),
        ).fetchall()
        products_catalog = [
            {"name": r[0], "qty": float(r[1] or 0), "rev": float(r[2] or 0)}
            for r in catalog_rows
        ]
        return {
            "label": f"Vendite IMS ({y}) – da fatturato (filtro: nessun dato)",
            "year": y,
            "provinces": [],
            "months": _MONTHS_IT,
            "byProvince": {},
            "topProducts": [],
            "productsCatalog": products_catalog,
            "filteredEmpty": True,
        }

    top_rows = conn.execute(
        f"""
        SELECT p.articolo, SUM(s.pieces), SUM(s.value)
        FROM sales s
        INNER JOIN products p ON s.product_catalog_id = p.catalog_id
        WHERE s.year = ?{pf_sql}{_sql_exclude_pseudo_product("p.articolo")}
        GROUP BY p.articolo
        ORDER BY SUM(s.value) DESC
        LIMIT 15
        """,
        (y,) + pf_args,
    ).fetchall()
    top_products = [
        {"name": r[0], "qty": float(r[1] or 0), "rev": float(r[2] or 0)} for r in top_rows
    ]

    catalog_rows = conn.execute(
        f"""
        SELECT p.articolo, SUM(s.pieces), SUM(s.value)
        FROM sales s
        INNER JOIN products p ON s.product_catalog_id = p.catalog_id
        WHERE s.year = ? AND p.articolo IS NOT NULL AND TRIM(p.articolo) != ''
        {_sql_exclude_pseudo_product("p.articolo")}
        GROUP BY p.articolo
        ORDER BY SUM(s.value) DESC
        """,
        (y,),
    ).fetchall()
    products_catalog = [
        {"name": r[0], "qty": float(r[1] or 0), "rev": float(r[2] or 0)} for r in catalog_rows
    ]

    prov_sorted = sorted(provs)
    return {
        "label": f"Vendite IMS ({y}) – da fatturato",
        "year": y,
        "provinces": prov_sorted,
        "months": _MONTHS_IT,
        "byProvince": {p: byp[p] for p in prov_sorted},
        "topProducts": top_products,
        "productsCatalog": products_catalog,
    }


def build_dashboard_dataset(
    conn: sqlite3.Connection,
    year: int | None = None,
    product_filter: frozenset[str] | None = None,
) -> dict | None:
    """Roll up ``sales`` only (via ``products`` join)."""
    return build_sales_dashboard_dataset(conn, year, product_filter=product_filter)
