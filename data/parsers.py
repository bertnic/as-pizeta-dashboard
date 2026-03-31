"""
Extract normalized measure rows from SEDRAN-style Excel sheets and monthly PDF reports.

Layout workbook **datalake** (es. ``DATABASE.xlsx`` — pivot copiati senza sorgente):

**Foglio 2025** (es. mesi 1–10):
- Riga header ``kProvincia`` (tipicamente sotto i titoli): col. **B** = provincia ripetuta a blocchi
  (un valore in B vale per tutte le righe del blocco fino al totale di provincia); **C** = prodotto.
- Col. **D–M** = pezzi per mese (intestazioni mese in riga header); **N–W** = fatturato per mese.
- Righe **totali di provincia** (es. 30, 53, …) e **totale complessivo** (es. riga ~123): colonna
  prodotto con etichette tipo *Totale* → **non** importate.
- Col. **X–Y** = totali di riga per prodotto (pezzi/fatturato) → **non** importati (doppio conteggio
  rispetto ai valori mensili).

**Foglio 20xx** (es. **2026**): stessa griglia ``kProvincia`` **oppure** layout pivot con
*Etichette di riga* e coppie (QIMS, Fat) per mese; ultime colonne *totale* riga → ignorate.

**SEDRAN** (mesi 10–12 2025 o simile): col. B = provincia a 2 lettere poi prodotti; righe agente
(etichetta che contiene ``SEDRAN``) resettano il contesto e **non** sono prodotti.

**ZIDOVAL 2025**: tabella semplice vendite per provincia/area e mese.

**PDF**: come griglia 2025 (solo celle mensili; niente totali riga in DB).

**Foglio ``DATABASE``** (workbook unico tipo ``DATABASE.xlsx``): tabella long-form
``COD | ARTICOLO | PROV | ANNO | MESE | PEZZI | FATTURATO | TARGET``; opzionale foglio
``ARTICOLI`` con prezzi → ``parse_database_workbook``.
Righe con **solo** ``TARGET`` (PEZZI/FATTURATO vuoti) sono importate come target.
Foglio opzionale **``TARGET``** (stesso workbook): griglia completa provincia×mese×prodotto
senza vendite; in caso di stessa chiave, il foglio ``TARGET`` **sovrascrive** il target letto da ``DATABASE``.

Altrove: **PHARMACIES**, **DB**, **ONLINE** → vedi funzioni dedicate.
Province **CO** e **CR** escluse.

Optional loader: ``apps/dashboard/data/etl_build_db.py`` (scrive il mart in ``pizeta.sqlite``).

**Workbook manuale:** titoli TARGET / PREZZI|PRODOTTI / FATTURATO → SQLite ``target``, ``products``, ``sales``.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import pdfplumber

Row = dict[str, Any]

# Province codes excluded from analytics (non rilevanti)
EXCLUDED_PROVINCE_CODES = frozenset({"CO", "CR"})

# Foglio manuale: titoli blocco in col. A (TARGET / PREZZI|PRODOTTI / FATTURATO) → SQLite target, products, sales
SHEET_MANUAL_TARGET_PREZZI = "1TQAGiWBTbYf9IPUqrhS9DBv5WFftDPqI"

# Legacy: foglio Google (ID) con righe fatturato → SQLite sales
SHEET_VENDITE_SEMI = "1W7R3_Few1FfqUgBzm2ep3AKRqBNyl6E2"
# Long-form sales (stesso significato di export formula → tab DB): un foglio unico
SHEET_DB_SALES = "DB"
# Griglia mensile cod | prodotto | provincia | pezzi 1..N | valore 1..N (come PHARMACIES nel workbook di riferimento)
SHEET_PHARMACIES = "PHARMACIES"

# Workbook canonico consigliato (altri SEDRAN (*.xlsx) sono duplicati)
CANONICAL_XLSX_NAMES = frozenset(
    {"SEDRAN (1).xlsx", "SEDRAN DEF..xlsx", "SEDRAN copia.xlsx"}
)


def _province_excluded(code: str | None) -> bool:
    if code is None:
        return False
    s = str(code).strip().upper()
    return s in EXCLUDED_PROVINCE_CODES


def _is_numeric_measure_cell(v: Any) -> bool:
    """True for int/float (incl. numpy scalars from Excel); excludes bool."""
    if pd.isna(v) or isinstance(v, bool):
        return False
    return bool(pd.api.types.is_number(v))


def _row(
    sheet: str,
    metric: str,
    value: float,
    *,
    geo_code: str | None = None,
    geo_label: str | None = None,
    agent_name: str | None = None,
    hierarchy_level: str | None = None,
    product_name: str | None = None,
    product_cod: str | None = None,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
) -> Row:
    d: Row = {
        "sheet": sheet,
        "geo_code": geo_code,
        "geo_label": geo_label,
        "agent_name": agent_name,
        "hierarchy_level": hierarchy_level,
        "product_name": product_name,
        "year": year,
        "month": month,
        "day": day,
        "metric": metric,
        "value": float(value),
    }
    if product_cod is not None:
        d["product_cod"] = product_cod
    return d


def _find_header_row(df: pd.DataFrame, marker: str = "kProvincia") -> int | None:
    for r in range(min(30, len(df))):
        v = df.iat[r, 1]
        if isinstance(v, str) and v.strip() == marker:
            return r
    return None


def _infer_monthly_grid_months(width: int, *, include_fat: bool) -> int:
    """Max month columns that fit kProvincia grid (pieces from col 3; optional Fat block + row totals)."""
    if include_fat:
        return min(12, max(0, (width - 4) // 2))
    return min(12, max(0, width - 3))


def _find_pivot_etiquette_row(df: pd.DataFrame) -> int | None:
    """Excel pivot export: col B row label 'Etichette di riga', then QIMS / Fat pairs per month."""
    for r in range(min(25, len(df))):
        v = df.iat[r, 1]
        if isinstance(v, str) and "Etichette di riga" in v:
            return r
    return None


def _is_two_letter_province_label(lab: str) -> bool:
    s = lab.strip().upper()
    return len(s) == 2 and s.isalpha()


def is_pivot_aggregate_product_name(name: str | None) -> bool:
    """
    True se l'etichetta in colonna prodotto è un subtotale/totale pivot, non uno SKU.
    ``None`` / vuoto → False (es. righe ZIDOVAL senza prodotto).
    """
    if name is None or not str(name).strip():
        return False
    s = str(name).strip()
    sl = s.lower()
    if sl == "articolo":
        return True
    if "totale" in sl or "subtotale" in sl or "sub-totale" in sl:
        return True
    if sl in ("total", "totals"):
        return True
    if sl.startswith("somma ") or "somma di" in sl:
        return True
    if _is_two_letter_province_label(s):
        return True
    return False


def parse_sheet_pivot_province_product_pairs(
    df: pd.DataFrame,
    *,
    sheet_code: str,
    year: int,
) -> list[Row]:
    """
    Pivot-style sheet (e.g. ``2026`` in SEDRAN copia): col B = agent / 2-letter prov / product;
    then pairs (QIMS, FatIMS) per month and optional final (QIMS totale, Fat totale).
    Agent and province subtotal rows without active province are skipped to avoid double counting.
    """
    out: list[Row] = []
    hr = _find_pivot_etiquette_row(df)
    if hr is None or df.shape[1] < 6:
        return out

    w = df.shape[1]
    n_pairs = (w - 2) // 2
    if n_pairs < 1:
        return out
    last_pair_start = 2 + (n_pairs - 1) * 2
    h0 = df.iat[hr, last_pair_start]
    has_totals_pair = isinstance(h0, str) and "totale" in h0.lower()
    n_months = min(12, n_pairs - 1 if has_totals_pair else n_pairs)
    if n_months < 1:
        return out

    current_province: str | None = None
    for r in range(hr + 1, len(df)):
        lab_v = df.iat[r, 1]
        if pd.isna(lab_v):
            continue
        lab = str(lab_v).strip()
        if not lab or lab.lower() == "etichette di riga":
            continue

        if _is_two_letter_province_label(lab):
            pu = lab.strip().upper()
            current_province = None if _province_excluded(pu) else pu
            continue

        if current_province is None:
            continue

        product = lab
        if is_pivot_aggregate_product_name(product):
            continue
        for mi in range(n_months):
            c0 = 2 + mi * 2
            qv = df.iat[r, c0]
            fv = df.iat[r, c0 + 1]
            if _is_numeric_measure_cell(qv):
                out.append(
                    _row(
                        sheet_code,
                        "pieces",
                        float(qv),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=mi + 1,
                    )
                )
            if _is_numeric_measure_cell(fv):
                out.append(
                    _row(
                        sheet_code,
                        "revenue",
                        float(fv),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=mi + 1,
                    )
                )

    return out


def parse_sheet_monthly_province_product(
    df: pd.DataFrame,
    *,
    sheet_code: str,
    year: int,
    max_months: int | None = 10,
    include_fat: bool = True,
) -> list[Row]:
    """
    Sheets '2025' and 'CR-CO': kProvincia | Articolo | QIMS m1..mN | [FatIMS m1..mN] | [col. totali riga].
    Le colonne totali riga (es. X–Y) **non** vengono lette — solo i valori mensili.
    If ``max_months`` is None, month count is inferred from column width (e.g. short YTD grids).
    """
    out: list[Row] = []
    hr = _find_header_row(df)
    if hr is None:
        return out

    n_months = (
        max_months
        if max_months is not None
        else _infer_monthly_grid_months(df.shape[1], include_fat=include_fat)
    )
    if n_months <= 0:
        return out
    # Col. C (index 2) = articolo; D.. = pezzi (n mesi); blocco fatturato subito dopo (es. N..W).
    fat_start = 3 + n_months
    min_w = fat_start + n_months if include_fat else 3 + n_months
    if df.shape[1] < min_w:
        return out

    current_province: str | None = None
    for r in range(hr + 1, len(df)):
        prov = df.iat[r, 1]
        art = df.iat[r, 2]
        if pd.isna(prov) and pd.isna(art):
            continue
        if isinstance(prov, str) and prov.strip():
            current_province = prov.strip()
        if not current_province:
            continue
        if _province_excluded(current_province):
            continue
        if pd.isna(art) or (isinstance(art, str) and not str(art).strip()):
            continue
        product = str(art).strip()
        if product.lower() == "articolo":
            continue
        if is_pivot_aggregate_product_name(product):
            continue

        for mi in range(n_months):
            qv = df.iat[r, 3 + mi]
            if _is_numeric_measure_cell(qv):
                out.append(
                    _row(
                        sheet_code,
                        "pieces",
                        float(qv),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=mi + 1,
                    )
                )
        if include_fat:
            for mi in range(n_months):
                fv = df.iat[r, fat_start + mi]
                if _is_numeric_measure_cell(fv):
                    out.append(
                        _row(
                            sheet_code,
                            "revenue",
                            float(fv),
                            geo_code=current_province,
                            hierarchy_level="product",
                            product_name=product,
                            year=year,
                            month=mi + 1,
                        )
                    )
    return out


def parse_pharmacies_wide_sheet(df: pd.DataFrame, *, year: int = 2025) -> list[dict[str, Any]]:
    """
    Griglia **cod | nome | provincia | M1..Mn pezzi | M1..Mn valore** (stesso layout della
    formula su colonne D–O + P–AA per 12 mesi). ``n`` = ``(cols - 3) // 2`` (es. 10 o 12).
    Produce righe ``sales`` (articolo, year, month, prov, pieces, value, cod opzionale).
    """
    if df.shape[1] < 5:
        return []
    n_months = (df.shape[1] - 3) // 2
    if n_months < 1:
        return []
    first_val_block = 3 + n_months
    if first_val_block + n_months > df.shape[1]:
        return []

    data_start = 0
    for r in range(min(8, len(df))):
        a = df.iat[r, 0]
        if isinstance(a, str) and a.strip().lower() in ("cod", "codice", "code", "id"):
            data_start = r + 1
            break

    out: list[dict[str, Any]] = []
    for r in range(data_start, len(df)):
        cod_v = df.iat[r, 0]
        art = df.iat[r, 1]
        prov = df.iat[r, 2]
        if pd.isna(art) or not str(art).strip():
            continue
        prov_s = str(prov).strip() if pd.notna(prov) else ""
        if not prov_s or _province_excluded(prov_s):
            continue
        cod_s = str(cod_v).strip() if pd.notna(cod_v) and str(cod_v).strip() else None
        product = str(art).strip()
        if product.lower() in ("name", "nome", "articolo", "product"):
            continue
        if is_pivot_aggregate_product_name(product):
            continue

        for mi in range(n_months):
            qv = df.iat[r, 3 + mi]
            fv = df.iat[r, first_val_block + mi]
            if pd.isna(qv) and pd.isna(fv):
                continue
            if not _is_numeric_measure_cell(qv) or not _is_numeric_measure_cell(fv):
                continue
            out.append(
                {
                    "cod": cod_s,
                    "articolo": product,
                    "year": year,
                    "month": mi + 1,
                    "prov": prov_s,
                    "pieces": float(qv),
                    "value": float(fv),
                }
            )
    return out


def parse_sheet_zidoval(df: pd.DataFrame) -> list[Row]:
    out: list[Row] = []
    if df.shape[0] < 3 or df.shape[1] < 3:
        return out
    months: list[tuple[int, int]] = []
    for c in range(2, df.shape[1]):
        dt = df.iat[1, c]
        if pd.isna(dt):
            continue
        if isinstance(dt, datetime):
            months.append((dt.year, dt.month))
        else:
            try:
                parsed = pd.to_datetime(dt)
                months.append((int(parsed.year), int(parsed.month)))
            except Exception:
                continue
    for r in range(2, len(df)):
        region = df.iat[r, 1]
        if pd.isna(region) or not str(region).strip():
            continue
        label = str(region).strip()
        for j, (y, m) in enumerate(months):
            c = 2 + j
            if c >= df.shape[1]:
                break
            v = df.iat[r, c]
            if pd.notna(v) and isinstance(v, (int, float)):
                out.append(
                    _row(
                        "ZIDOVAL 2025",
                        "pieces",
                        float(v),
                        geo_label=label,
                        hierarchy_level="na",
                        year=y,
                        month=m,
                    )
                )
    return out


def _parse_online_money_cell(v: Any) -> float | None:
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("€", "").replace("EUR", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _find_online_header_row_shopify(df: pd.DataFrame) -> int | None:
    for r in range(min(15, len(df))):
        row_vals = [df.iat[r, c] for c in range(min(8, df.shape[1]))]
        joined = " ".join(str(x) for x in row_vals if pd.notna(x))
        if "Order Date" in joined and "Item Name" in joined:
            return r
    return None


def _find_online_header_row_tabular(df: pd.DataFrame) -> int | None:
    """Layout Data | Prov | … | cod | nome | pezzi (prime 6 colonne)."""
    for r in range(min(25, len(df))):
        cells = [str(df.iat[r, c]).strip().lower() for c in range(min(6, df.shape[1]))]
        joined = " ".join(cells)
        if "data" not in joined:
            continue
        if "prov" not in joined and "provincia" not in joined:
            continue
        if not any(x in joined for x in ("pezzi", "qty", "qta", "quant")):
            continue
        return r
    return None


def parse_sheet_online_shopify(df: pd.DataFrame) -> list[Row]:
    out: list[Row] = []
    header_r = _find_online_header_row_shopify(df)
    if header_r is None:
        return out

    for r in range(header_r + 1, len(df)):
        od = df.iat[r, 2]
        st = df.iat[r, 3]
        net = df.iat[r, 4]
        item = df.iat[r, 5]
        qty = df.iat[r, 6]
        if pd.isna(od) and pd.isna(item):
            continue
        day_d: datetime | None = None
        if not pd.isna(od):
            try:
                day_d = pd.to_datetime(od).to_pydatetime()
            except Exception:
                day_d = None
        y, m, d = (day_d.year, day_d.month, day_d.day) if day_d else (None, None, None)
        geo = str(st).strip() if pd.notna(st) else None
        if _province_excluded(geo):
            continue
        prod = str(item).strip() if pd.notna(item) else None
        if prod:
            if pd.notna(qty) and isinstance(qty, (int, float)):
                out.append(
                    _row(
                        "ONLINE",
                        "pieces",
                        float(qty),
                        geo_code=geo,
                        hierarchy_level="order_line",
                        product_name=prod,
                        year=y,
                        month=m,
                        day=d,
                    )
                )
            if pd.notna(net) and isinstance(net, (int, float)):
                out.append(
                    _row(
                        "ONLINE",
                        "revenue",
                        float(net),
                        geo_code=geo,
                        hierarchy_level="order_line",
                        product_name=prod,
                        year=y,
                        month=m,
                        day=d,
                    )
                )
    return out


def parse_sheet_online_tabular(df: pd.DataFrame) -> list[Row]:
    """Righe giornaliere: data, provincia, importo, cod, nome, pezzi (colonne A–F)."""
    out: list[Row] = []
    hr = _find_online_header_row_tabular(df)
    if hr is None or df.shape[1] < 6:
        return out

    for r in range(hr + 1, len(df)):
        od = df.iat[r, 0]
        st = df.iat[r, 1]
        net_raw = df.iat[r, 2]
        cod_v = df.iat[r, 3]
        item = df.iat[r, 4]
        qty = df.iat[r, 5]
        if pd.isna(od) and pd.isna(item):
            continue
        day_d: datetime | None = None
        if not pd.isna(od):
            try:
                day_d = pd.to_datetime(od).to_pydatetime()
            except Exception:
                day_d = None
        y, m, d = (day_d.year, day_d.month, day_d.day) if day_d else (None, None, None)
        geo = str(st).strip() if pd.notna(st) else None
        if _province_excluded(geo):
            continue
        prod = str(item).strip() if pd.notna(item) else None
        if not prod:
            continue
        cod_s = str(cod_v).strip() if pd.notna(cod_v) and str(cod_v).strip() else None
        net = _parse_online_money_cell(net_raw)
        if pd.notna(qty) and isinstance(qty, (int, float)):
            out.append(
                _row(
                    "ONLINE",
                    "pieces",
                    float(qty),
                    geo_code=geo,
                    hierarchy_level="order_line",
                    product_name=prod,
                    product_cod=cod_s,
                    year=y,
                    month=m,
                    day=d,
                )
            )
        if net is not None:
            out.append(
                _row(
                    "ONLINE",
                    "revenue",
                    net,
                    geo_code=geo,
                    hierarchy_level="order_line",
                    product_name=prod,
                    product_cod=cod_s,
                    year=y,
                    month=m,
                    day=d,
                )
            )
    return out


def parse_sheet_online(df: pd.DataFrame) -> list[Row]:
    shop = parse_sheet_online_shopify(df)
    if shop:
        return shop
    return parse_sheet_online_tabular(df)


def _is_province_code(s: str) -> bool:
    s = s.strip()
    if len(s) < 2 or len(s) > 4:
        return False
    return s.isalpha() and s.upper() == s


def parse_sheet_sedran_pivot(df: pd.DataFrame, *, year: int = 2025) -> list[Row]:
    """
    SEDRAN sheet: agent row, then provinces with nested products; months 10–12 as QIMS/Fat pairs.
    """
    out: list[Row] = []
    if df.shape[1] < 9:
        return out

    months = [10, 11, 12]
    current_province: str | None = None
    agent: str | None = None

    for r in range(8, len(df)):
        label = df.iat[r, 1]
        if pd.isna(label) or not str(label).strip():
            continue
        label_s = str(label).strip()

        c2, c3, c4, c5, c6, c7 = [df.iat[r, c] for c in range(2, 8)]
        pairs_raw = [(months[0], c2, c3), (months[1], c4, c5), (months[2], c6, c7)]

        def emit_pairs(
            *,
            geo: str | None,
            agent: str | None,
            level: str,
            prod: str | None,
        ) -> None:
            for m, q, f in pairs_raw:
                if pd.notna(q) and isinstance(q, (int, float)):
                    out.append(
                        _row(
                            "SEDRAN",
                            "pieces",
                            float(q),
                            geo_code=geo,
                            agent_name=agent,
                            hierarchy_level=level,
                            product_name=prod,
                            year=year,
                            month=m,
                        )
                    )
                if pd.notna(f) and isinstance(f, (int, float)):
                    out.append(
                        _row(
                            "SEDRAN",
                            "revenue",
                            float(f),
                            geo_code=geo,
                            agent_name=agent,
                            hierarchy_level=level,
                            product_name=prod,
                            year=year,
                            month=m,
                        )
                    )

        has_any_measure = any(
            pd.notna(x) and isinstance(x, (int, float)) for x in (c2, c3, c4, c5, c6, c7)
        )
        if not has_any_measure:
            continue

        # Riga agente / intestazione: non è provincia né prodotto
        if "SEDRAN" in label_s.upper() and not _is_province_code(label_s):
            current_province = None
            continue

        if _is_province_code(label_s):
            current_province = label_s
            continue

        if current_province and not _province_excluded(current_province):
            if is_pivot_aggregate_product_name(label_s):
                continue
            prod = label_s
            emit_pairs(geo=current_province, agent=None, level="product", prod=prod)
            continue

    return out


def _valid_target_calendar_year_month(y: int, m: int) -> bool:
    """Scarta date parse spurie (es. interi letti come giorni epoch)."""
    return 2018 <= int(y) <= 2035 and 1 <= int(m) <= 12


def parse_sedran_def_targets_prezzi(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    SEDRAN DEF → righe per SQLite `target` (prov, articolo, year, month, pieces) e `products` (articolo, prezzo).
    Esclude province CO e CR.
    """
    targets: list[dict[str, Any]] = []
    prezzi_map: dict[str, float] = {}
    if df.shape[0] < 8 or df.shape[1] < 6:
        return targets, []

    months: list[tuple[int, int]] = []
    for c in range(3, min(df.shape[1], 20)):
        dt = df.iat[6, c]
        if pd.isna(dt):
            continue
        if isinstance(dt, datetime):
            y, m = int(dt.year), int(dt.month)
        else:
            try:
                p = pd.to_datetime(dt)
                y, m = int(p.year), int(p.month)
            except Exception:
                break
        if not _valid_target_calendar_year_month(y, m):
            break
        months.append((y, m))

    if not months:
        return targets, []

    n_m = len(months)
    tot_c = 3 + n_m
    price_c = tot_c + 1

    current_province: str | None = None
    for r in range(7, len(df)):
        pcell = df.iat[r, 1]
        acell = df.iat[r, 2]
        if isinstance(pcell, str) and pcell.strip():
            current_province = pcell.strip()
        if not current_province or pd.isna(acell):
            continue
        if _province_excluded(current_province):
            continue
        product = str(acell).strip()

        for j, (y, m) in enumerate(months):
            c = 3 + j
            v = df.iat[r, c]
            if pd.notna(v) and isinstance(v, (int, float)):
                targets.append(
                    {
                        "cod": None,
                        "prov": current_province,
                        "articolo": product,
                        "year": int(y),
                        "month": int(m),
                        "pieces": float(v),
                    }
                )
        if price_c < df.shape[1]:
            pv = df.iat[r, price_c]
            if pd.notna(pv) and isinstance(pv, (int, float)):
                prezzi_map[product] = float(pv)

    prezzi = [{"cod": None, "articolo": k, "prezzo": v} for k, v in sorted(prezzi_map.items())]
    return targets, prezzi


def is_sedran_def_workbook(path: Path) -> bool:
    return path.suffix.lower() == ".xlsx" and "DEF" in path.name.upper()


def read_sedran_sheet_raw(path: str | Path) -> pd.DataFrame | None:
    """Legge il foglio ``SEDRAN`` se esiste (qualsiasi nome file)."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        return None
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return None
    if "SEDRAN" not in xl.sheet_names:
        return None
    return pd.read_excel(path, sheet_name="SEDRAN", header=None)


def sedran_df_is_target_pricing_layout(df: pd.DataFrame) -> bool:
    """
    Layout DEF (target + prezzi): ``kProvincia`` in riga 6 (0-based), colonne ≥ 15.
    Stesso criterio usato in ``iter_rows_from_xlsx`` per **non** importare qui i fact.
    """
    if df.shape[0] < 8 or df.shape[1] < 15:
        return False
    hr = _find_header_row(df)
    return hr == 6


def read_sedran_def_sheet(path: Path) -> pd.DataFrame | None:
    if not is_sedran_def_workbook(path):
        return None
    return read_sedran_sheet_raw(path)


def _norm_header(s: str) -> str:
    return re.sub(r"\s+", "_", str(s).strip().upper())


def _pick_col(df: pd.DataFrame, *names: str) -> str | None:
    mapping = {_norm_header(c): c for c in df.columns}
    for n in names:
        key = _norm_header(n)
        if key in mapping:
            return mapping[key]
    return None


def _section_from_cell_a(cell: Any) -> str | None:
    if pd.isna(cell):
        return None
    s = str(cell).strip().upper().replace(".", "")
    if s in ("TARGET", "TARGETS"):
        return "TARGET"
    if s in ("PREZZI", "PREZZO", "PRODOTTI", "LISTINO", "LISTINO_PREZZI"):
        return "PREZZI"
    if s in ("FATTURATO", "VENDITE", "FATTURATI"):
        return "FATTURATO"
    return None


def _header_col_map(df: pd.DataFrame, header_row: int, max_col: int = 40) -> dict[str, int]:
    """Map normalized header → column index (first occurrence)."""
    m: dict[str, int] = {}
    for c in range(min(max_col, df.shape[1])):
        v = df.iat[header_row, c]
        if pd.isna(v):
            continue
        t = str(v).strip()
        if not t:
            continue
        key = _norm_header(t)
        if key and key not in m:
            m[key] = c
    return m


def _cell(df: pd.DataFrame, r: int, col_map: dict[str, int], *names: str) -> Any:
    for n in names:
        k = _norm_header(n)
        if k in col_map:
            return df.iat[r, col_map[k]]
    return None


def _fnum(x: Any) -> float | None:
    if pd.isna(x):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", "."))
    except ValueError:
        return None


def _fint(x: Any) -> int | None:
    v = _fnum(x)
    if v is None:
        return None
    return int(v)


def _row_blankish(df: pd.DataFrame, r: int, ncols: int = 12) -> bool:
    for c in range(min(ncols, df.shape[1])):
        v = df.iat[r, c]
        if pd.notna(v) and str(v).strip():
            return False
    return True


def parse_manual_target_prezzi_sheet(df: pd.DataFrame) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Foglio 1TQAG…: blocchi verticali. Riga con titolo in col. A (TARGET / PREZZI|PRODOTTI / FATTURATO),
    riga successiva = intestazioni, poi righe dati fino a riga vuota o nuovo titolo.

    Ritorna (target_rows, prodotti_rows, fatturato_rows) con chiavi allineate alle tabelle SQL.
    """
    targets: list[dict[str, Any]] = []
    prodotti: list[dict[str, Any]] = []
    fatturato: list[dict[str, Any]] = []
    if df is None or df.empty:
        return targets, prodotti, fatturato

    nrows, _ = df.shape
    r = 0
    while r < nrows:
        kind = _section_from_cell_a(df.iat[r, 0])
        if not kind:
            r += 1
            continue
        hr = r + 1
        if hr >= nrows:
            break
        col_map = _header_col_map(df, hr)
        if not col_map:
            r += 1
            continue
        r = hr + 1
        while r < nrows:
            if _section_from_cell_a(df.iat[r, 0]):
                break
            if _row_blankish(df, r):
                r += 1
                break
            if kind == "TARGET":
                art = _cell(df, r, col_map, "ARTICOLO", "PRODOTTO", "ART")
                if pd.isna(art) or not str(art).strip():
                    r += 1
                    continue
                prov = _cell(df, r, col_map, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
                prov_s = str(prov).strip() if pd.notna(prov) else ""
                if _province_excluded(prov_s or None):
                    r += 1
                    continue
                anno = _fint(_cell(df, r, col_map, "ANNO", "ANO", "YEAR", "A"))
                mese = _fint(_cell(df, r, col_map, "MESE", "MONTH", "M", "NUM_MESE"))
                qta_v = _fnum(_cell(df, r, col_map, "QTA", "QUANTITA", "QT", "PEZZI", "QIMS"))
                cod_v = _cell(df, r, col_map, "COD", "CODICE", "CODE", "ID")
                cod_s = str(cod_v).strip() if pd.notna(cod_v) else None
                if anno is None or mese is None or qta_v is None or not prov_s:
                    r += 1
                    continue
                targets.append(
                    {
                        "cod": cod_s,
                        "articolo": str(art).strip(),
                        "year": anno,
                        "month": mese,
                        "prov": prov_s,
                        "pieces": qta_v,
                    }
                )
            elif kind == "PREZZI":
                art = _cell(df, r, col_map, "ARTICOLO", "PRODOTTO", "ART")
                if pd.isna(art) or not str(art).strip():
                    r += 1
                    continue
                prezzo = _fnum(
                    _cell(df, r, col_map, "PREZZO", "PREZZO_IMS", "LISTINO", "P", "PRICE")
                )
                cod_v = _cell(df, r, col_map, "COD", "CODICE", "CODE", "ID")
                cod_s = str(cod_v).strip() if pd.notna(cod_v) else None
                if prezzo is None:
                    r += 1
                    continue
                prodotti.append(
                    {"cod": cod_s, "articolo": str(art).strip(), "prezzo": prezzo}
                )
            else:  # FATTURATO
                art = _cell(df, r, col_map, "ARTICOLO", "PRODOTTO", "ART")
                if pd.isna(art) or not str(art).strip():
                    r += 1
                    continue
                prov = _cell(df, r, col_map, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
                prov_s = str(prov).strip() if pd.notna(prov) else ""
                if _province_excluded(prov_s or None):
                    r += 1
                    continue
                anno = _fint(_cell(df, r, col_map, "ANNO", "ANO", "YEAR"))
                mese = _fint(_cell(df, r, col_map, "MESE", "MONTH", "M", "NUM_MESE"))
                qta_v = _fnum(_cell(df, r, col_map, "QTA", "QUANTITA", "QT", "PEZZI", "QIMS"))
                valore = _fnum(
                    _cell(df, r, col_map, "VALORE", "IMPORTO", "FATTURATO", "NETTO", "TOTALE")
                )
                cod_v = _cell(df, r, col_map, "COD", "CODICE", "CODE", "ID")
                cod_s = str(cod_v).strip() if pd.notna(cod_v) else None
                if anno is None or mese is None or qta_v is None or valore is None:
                    r += 1
                    continue
                fatturato.append(
                    {
                        "cod": cod_s,
                        "articolo": str(art).strip(),
                        "year": anno,
                        "month": mese,
                        "prov": prov_s or None,
                        "pieces": qta_v,
                        "value": valore,
                    }
                )
            r += 1
    return targets, prodotti, fatturato


def iter_manual_target_prezzi_fatturato(path: str | Path) -> tuple[list[dict], list[dict], list[dict]]:
    path = Path(path)
    xl = pd.ExcelFile(path)
    if SHEET_MANUAL_TARGET_PREZZI not in xl.sheet_names:
        return [], [], []
    df = pd.read_excel(path, sheet_name=SHEET_MANUAL_TARGET_PREZZI, header=None)
    return parse_manual_target_prezzi_sheet(df)


def parse_sheet_vendite_semi(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Normalizza il foglio semi-strutturato a: cod, articolo, prov, mese, pieces, value.
    Province CO/CR escluse.
    """
    if df is None or df.empty:
        return []

    cod_c = _pick_col(df, "COD", "CODICE", "ID", "CODE")
    art_c = _pick_col(df, "ARTICOLO", "PRODOTTO", "ART", "NAME", "NOME", "PRODUCT")
    prov_c = _pick_col(df, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    mes_c = _pick_col(df, "MESE", "MONTH", "NUM_MESE", "M")
    qta_c = _pick_col(df, "QTA", "QUANTITA", "QT", "PEZZI", "QIMS", "PIECES")
    val_c = _pick_col(
        df, "VALORE", "VALUE", "IMPORTO", "TOTALE", "FATTURATO", "NETTO", "TOT_NETTO"
    )
    anno_c = _pick_col(df, "ANNO", "ANO", "YEAR")

    if not art_c or not mes_c or not qta_c or not val_c:
        return []

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        art = row.get(art_c)
        if pd.isna(art) or not str(art).strip():
            continue
        prov = None
        if prov_c:
            v = row.get(prov_c)
            if pd.notna(v):
                prov = str(v).strip()
        if _province_excluded(prov):
            continue
        try:
            mese = int(float(row[mes_c]))
        except (TypeError, ValueError):
            continue
        try:
            qta = float(row[qta_c])
        except (TypeError, ValueError):
            continue
        try:
            valore = float(row[val_c])
        except (TypeError, ValueError):
            continue
        cod = None
        if cod_c:
            cv = row.get(cod_c)
            if pd.notna(cv):
                cod = str(cv).strip()
        anno = 2025
        if anno_c and pd.notna(row.get(anno_c)):
            try:
                anno = int(float(row[anno_c]))
            except (TypeError, ValueError):
                pass
        out.append(
            {
                "cod": cod,
                "articolo": str(art).strip(),
                "year": anno,
                "month": mese,
                "prov": prov,
                "pieces": qta,
                "value": valore,
            }
        )
    return out


def workbook_sales_source(
    path: str | Path,
) -> tuple[str | None, list[dict[str, Any]]]:
    """
    Restituisce (origine, righe ``sales``) se il workbook ha un foglio long-form **DB**,
    il foglio legacy per ID, oppure **PHARMACIES** (+ ONLINE aggregato per mese).
    Origine: ``\"db\"`` | ``\"legacy_sheet\"`` | ``\"pharmacies\"`` | ``None``.
    """
    path = Path(path)
    xl = pd.ExcelFile(path)
    for sheet, kind in ((SHEET_DB_SALES, "db"), (SHEET_VENDITE_SEMI, "legacy_sheet")):
        if sheet in xl.sheet_names:
            df = pd.read_excel(path, sheet_name=sheet, header=0)
            rows = parse_sheet_vendite_semi(df)
            if rows:
                return kind, rows
    if SHEET_PHARMACIES in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=SHEET_PHARMACIES, header=None)
        ph = parse_pharmacies_wide_sheet(df, year=2025)
        on_rows: list[Row] = []
        if "ONLINE" in xl.sheet_names:
            df_o = pd.read_excel(path, sheet_name="ONLINE", header=None)
            on_rows = parse_sheet_online(df_o)
        ph.extend(aggregate_online_rows_to_monthly_sales(on_rows))
        if ph:
            return "pharmacies", ph
    return None, []


def iter_workbook_sales_rows(path: str | Path) -> list[dict[str, Any]]:
    _, rows = workbook_sales_source(path)
    return rows


def workbook_skip_online_for_fact(path: str | Path) -> bool:
    """
    True se ONLINE è già coperto dalle righe ``sales`` (foglio **DB** oppure **PHARMACIES**
    + aggregato mensile ONLINE) → non duplicare in ``fact_measure``.
    """
    path = Path(path)
    xl = pd.ExcelFile(path)
    if SHEET_DB_SALES in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=SHEET_DB_SALES, header=0)
        if parse_sheet_vendite_semi(df):
            return True
    if SHEET_PHARMACIES in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=SHEET_PHARMACIES, header=None)
        if parse_pharmacies_wide_sheet(df, year=2025):
            return True
    return False


def aggregate_online_rows_to_monthly_sales(rows: list[Row]) -> list[dict[str, Any]]:
    """Somma giornaliera ONLINE in righe mensili ``sales`` (stesso gruppo della QUERY Sheets)."""
    from collections import defaultdict

    pieces_acc: dict[tuple[str, str, str | None, int, int], float] = defaultdict(float)
    revenue_acc: dict[tuple[str, str, str | None, int, int], float] = defaultdict(float)

    def key(r: Row) -> tuple[str, str, str | None, int, int] | None:
        y, m = r.get("year"), r.get("month")
        if y is None or m is None:
            return None
        prov = r.get("geo_code")
        prov_s = str(prov).strip() if prov is not None and str(prov).strip() else None
        pn = (r.get("product_name") or "").strip()
        if not pn:
            return None
        cod = r.get("product_cod")
        cod_s = str(cod).strip() if cod is not None and str(cod).strip() else ""
        return (cod_s, pn, prov_s, int(y), int(m))

    for r in rows:
        if r.get("sheet") != "ONLINE" or r.get("hierarchy_level") != "order_line":
            continue
        met = r.get("metric")
        if met not in ("pieces", "revenue"):
            continue
        k = key(r)
        if k is None:
            continue
        if met == "pieces":
            pieces_acc[k] += float(r["value"])
        else:
            revenue_acc[k] += float(r["value"])

    out: list[dict[str, Any]] = []
    for k in sorted(set(pieces_acc) | set(revenue_acc)):
        cod_s, pn, prov_s, y, m = k
        pv = pieces_acc.get(k, 0.0)
        rv = revenue_acc.get(k, 0.0)
        if pv == 0.0 and rv == 0.0:
            continue
        out.append(
            {
                "cod": cod_s or None,
                "articolo": pn,
                "year": y,
                "month": m,
                "prov": prov_s,
                "pieces": pv,
                "value": rv,
            }
        )
    return out


def iter_vendite_semi_rows(path: str | Path) -> list[dict[str, Any]]:
    """Compat: stesso contratto di ``iter_workbook_sales_rows``."""
    return iter_workbook_sales_rows(path)


_FLOAT_RE = re.compile(r"^-?\d+([.,]\d+)?$")


def _parse_num(tok: str) -> float | None:
    if not _FLOAT_RE.match(tok):
        return None
    try:
        return float(tok.replace(",", "."))
    except ValueError:
        return None


def _parse_pdf_data_line(line: str, last_province: str | None) -> tuple[list[Row], str | None] | None:
    line = line.strip()
    if not line or "Totale" in line or "kProvinc" in line or "Articolo" in line:
        return None

    tokens = line.split()
    if len(tokens) < 15:
        return None

    nums: list[float] = []
    i = len(tokens) - 1
    while i >= 0:
        v = _parse_num(tokens[i])
        if v is None:
            break
        nums.append(v)
        i -= 1
    nums.reverse()
    if len(nums) < 22:
        return None

    rest = tokens[: i + 1]
    if not rest:
        return None

    province: str | None = None
    product_start = 0
    if len(rest[0]) == 2 and rest[0].isalpha() and rest[0].upper() == rest[0]:
        province = rest[0].upper()
        product_start = 1
    else:
        province = last_province

    if province is None or _province_excluded(province):
        return None

    product = " ".join(rest[product_start:]).strip() if product_start < len(rest) else ""
    if not product or is_pivot_aggregate_product_name(product):
        return None

    fat_vals = nums[-12:-2]
    qims_vals = nums[:-12]

    if len(qims_vals) != 10 or len(fat_vals) != 10:
        return None

    out: list[Row] = []
    for mi, q in enumerate(qims_vals):
        out.append(
            _row(
                "PDF_MONTHLY",
                "pieces",
                q,
                geo_code=province,
                hierarchy_level="product",
                product_name=product,
                year=2025,
                month=mi + 1,
            )
        )
    for mi, f in enumerate(fat_vals):
        out.append(
            _row(
                "PDF_MONTHLY",
                "revenue",
                f,
                geo_code=province,
                hierarchy_level="product",
                product_name=product,
                year=2025,
                month=mi + 1,
            )
        )
    return out, province


def parse_pdf_monthly(path: str | Path) -> list[Row]:
    out: list[Row] = []
    last_province: str | None = None
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                parsed = _parse_pdf_data_line(line, last_province)
                if not parsed:
                    continue
                rows, last_province = parsed
                out.extend(rows)
    return out


def workbook_is_database_longform(path: str | Path) -> bool:
    """True se esiste il foglio ``DATABASE`` con header che inizia da ``COD`` (formato long-form)."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        return False
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return False
    if "DATABASE" not in xl.sheet_names:
        return False
    df = pd.read_excel(path, sheet_name="DATABASE", header=None, nrows=1)
    if df.empty or df.shape[1] < 6:
        return False
    return str(df.iat[0, 0]).strip().upper() == "COD"


def _sheet_name_ci(xl: pd.ExcelFile, want: str) -> str | None:
    w = want.strip().upper()
    for name in xl.sheet_names:
        if str(name).strip().upper() == w:
            return name
    return None


def _norm_cod_lookup_key(v: Any) -> str:
    """Chiave di join tra fogli su COD (stringa o numero Excel)."""
    if pd.isna(v) or isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        if isinstance(v, int):
            return str(v)
        return str(v).strip().upper()
    s = str(v).strip()
    if not s:
        return ""
    try:
        f = float(s.replace(",", "."))
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s.upper()


def _excel_catalog_id(v: Any) -> int | None:
    try:
        if pd.isna(v):
            return None
        i = int(float(v))
        return i
    except (TypeError, ValueError):
        return None


def _catalog_id_str(v: Any) -> str | None:
    """ID articolo da foglio ARTICOLI (numerico o testo, es. ``ALDET``, ``42``)."""
    if pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


def workbook_is_database_mart_v2(path: str | Path) -> bool:
    """
    Workbook ``DATABASE.xlsx`` (datalake) con tre fogli: **VENDITE**, **ARTICOLI**, **TARGET**.
    ``COD`` su VENDITE/TARGET → riga in ARTICOLI; colonna **ID** in ARTICOLI → ``product_catalog_id`` in SQLite.
    """
    path = Path(path)
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        return False
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return False
    return (
        _sheet_name_ci(xl, "VENDITE") is not None
        and _sheet_name_ci(xl, "ARTICOLI") is not None
        and _sheet_name_ci(xl, "TARGET") is not None
    )


def parse_database_mart_workbook(
    path: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Legge fogli **ARTICOLI** (ID, COD, ARTICOLO, PREZZO), **VENDITE**, **TARGET**.

    Ritorna ``(products_rows, sales_rows, target_rows)`` per l'ETL:
    prodotti ``catalog_id``, ``articolo``, ``prezzo`` (prezzo troncato a 2 decimali);
    vendite/target solo ``product_catalog_id``, date geografiche, ``pieces`` (intero), ``value`` (solo vendite).
    """
    path = Path(path)
    xl = pd.ExcelFile(path)
    sn_art = _sheet_name_ci(xl, "ARTICOLI")
    sn_ven = _sheet_name_ci(xl, "VENDITE")
    sn_tgt = _sheet_name_ci(xl, "TARGET")
    if not sn_art or not sn_ven or not sn_tgt:
        return [], [], []

    def col_df(df: pd.DataFrame, *names: str):
        cmap = {re.sub(r"\s+", "_", str(c).strip().upper()): c for c in df.columns}
        for n in names:
            k = re.sub(r"\s+", "_", n.strip().upper())
            if k in cmap:
                return cmap[k]
        return None

    dfa = pd.read_excel(path, sheet_name=sn_art, header=0)
    c_id = col_df(dfa, "ID", "ID_ARTICOLO", "ID_PRODOTTO", "SKU_ID")
    c_cod_a = col_df(dfa, "COD", "CODICE", "CODE", "COD_ART")
    c_art = col_df(dfa, "ARTICOLO", "PRODOTTO", "ART", "DESCRIZIONE")
    c_pre = col_df(dfa, "PREZZO", "PREZZO_IMS", "PRICE", "PREZZO_LISTINO")
    if not c_id or not c_art or not c_pre:
        return [], [], []

    by_cod: dict[str, dict[str, Any]] = {}
    products_by_cat: dict[str, dict[str, Any]] = {}

    for _, row in dfa.iterrows():
        cid = _catalog_id_str(row[c_id])
        if cid is None:
            continue
        art_raw = row[c_art]
        if pd.isna(art_raw) or not str(art_raw).strip():
            continue
        articolo = str(art_raw).strip()
        if is_pivot_aggregate_product_name(articolo):
            continue
        if c_cod_a is not None and pd.notna(row[c_cod_a]) and str(row[c_cod_a]).strip():
            cod_key = _norm_cod_lookup_key(row[c_cod_a])
            cod_disp = row[c_cod_a]
            cod_s = None if pd.isna(cod_disp) else str(cod_disp).strip()
        else:
            # Foglio ARTICOLI senza COD: VENDITE/TARGET usano COD = ID catalogo (stesso valore in cella COD).
            cod_key = _norm_cod_lookup_key(cid)
            cod_s = cid
        if not cod_key:
            continue
        pv = row[c_pre]
        prezzo = float(pv) if _is_numeric_measure_cell(pv) else 0.0
        prezzo = int(prezzo * 100) / 100.0
        if not cod_s:
            cod_s = cod_key
        rec = {
            "catalog_id": cid,
            "articolo": articolo,
            "prezzo": prezzo,
        }
        by_cod[cod_key] = dict(rec)
        products_by_cat[cid] = dict(rec)

    products = sorted(products_by_cat.values(), key=lambda p: p["catalog_id"])

    dfv = pd.read_excel(path, sheet_name=sn_ven, header=0)
    c_cod_v = col_df(dfv, "COD", "CODICE", "CODE")
    c_prov_v = col_df(dfv, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    c_anno_v = col_df(dfv, "ANNO", "ANO", "YEAR")
    c_mese_v = col_df(dfv, "MESE", "MONTH", "M", "NUM_MESE")
    c_pezzi = col_df(dfv, "PEZZI", "QTA", "QUANTITA", "PIECES", "QIMS")
    c_fat = col_df(dfv, "FATTURATO", "VALORE", "IMPORTO", "REVENUE", "VALUE", "FAT")
    if not c_cod_v or not c_prov_v or not c_anno_v or not c_mese_v:
        return products, [], []

    sales_out: list[dict[str, Any]] = []
    for _, row in dfv.iterrows():
        ck = _norm_cod_lookup_key(row[c_cod_v])
        info = by_cod.get(ck)
        if not info:
            continue
        prov_raw = row[c_prov_v]
        if pd.isna(prov_raw):
            continue
        prov = str(prov_raw).strip().upper()
        if _province_excluded(prov):
            continue
        try:
            anno = int(float(row[c_anno_v]))
            mese = int(float(row[c_mese_v]))
            if not (1 <= mese <= 12) or not (2018 <= anno <= 2035):
                continue
        except (TypeError, ValueError):
            continue
        has_p = c_pezzi is not None and _is_numeric_measure_cell(row[c_pezzi])
        has_f = c_fat is not None and _is_numeric_measure_cell(row[c_fat])
        if not has_p and not has_f:
            continue
        art_l = info["articolo"].strip().lower()
        if art_l == "totale complessivo":
            continue
        pieces = int(float(row[c_pezzi])) if has_p else 0
        value = float(row[c_fat]) if has_f else 0.0
        sales_out.append(
            {
                "product_catalog_id": info["catalog_id"],
                "year": anno,
                "month": mese,
                "prov": prov,
                "pieces": pieces,
                "value": value,
            }
        )

    dft = pd.read_excel(path, sheet_name=sn_tgt, header=0)
    c_cod_t = col_df(dft, "COD", "CODICE", "CODE")
    c_prov_t = col_df(dft, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    c_anno_t = col_df(dft, "ANNO", "ANO", "YEAR")
    c_mese_t = col_df(dft, "MESE", "MONTH", "M", "NUM_MESE")
    c_tgt = col_df(
        dft,
        "TARGET",
        "TARGET_PEZZI",
        "TARGET_QTY",
        "TARGET_QIMS",
        "PEZZI_TARGET",
        "PEZZI",
    )
    if not c_cod_t or not c_prov_t or not c_anno_t or not c_mese_t or not c_tgt:
        return products, sales_out, []

    targets_out: list[dict[str, Any]] = []
    for _, row in dft.iterrows():
        ck = _norm_cod_lookup_key(row[c_cod_t])
        info = by_cod.get(ck)
        if not info:
            continue
        prov_raw = row[c_prov_t]
        if pd.isna(prov_raw):
            continue
        prov = str(prov_raw).strip().upper()
        if _province_excluded(prov):
            continue
        try:
            anno = int(float(row[c_anno_t]))
            mese = int(float(row[c_mese_t]))
            if not (1 <= mese <= 12) or not (2018 <= anno <= 2035):
                continue
        except (TypeError, ValueError):
            continue
        tv = row[c_tgt]
        if not _is_numeric_measure_cell(tv) or float(tv) <= 0:
            continue
        art_l = info["articolo"].strip().lower()
        if art_l == "totale complessivo":
            continue
        targets_out.append(
            {
                "product_catalog_id": info["catalog_id"],
                "year": anno,
                "month": mese,
                "prov": prov,
                "pieces": int(float(tv)),
            }
        )

    return products, sales_out, targets_out


def _parse_database_target_only_dataframe(
    df: pd.DataFrame,
) -> dict[tuple[str, str, int, int], dict[str, Any]]:
    """
    Long-form target rows: stesse chiavi del foglio DATABASE, senza colonne vendite.
    Chiave dedup: (articolo upper, prov, anno, mese).
    """
    out: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    colmap = {re.sub(r"\s+", "_", str(c).strip().upper()): c for c in df.columns}

    def col(*names: str):
        for n in names:
            k = re.sub(r"\s+", "_", n.strip().upper())
            if k in colmap:
                return colmap[k]
        return None

    c_cod = col("COD", "CODICE", "CODE")
    c_art = col("ARTICOLO", "PRODOTTO", "ART")
    c_prov = col("PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    c_anno = col("ANNO", "ANO", "YEAR")
    c_mese = col("MESE", "MONTH", "M", "NUM_MESE")
    c_tgt = col("TARGET", "TARGET_PEZZI", "TARGET_QTY", "TARGET_QIMS", "PEZZI_TARGET")
    if not c_art or not c_prov or not c_anno or not c_mese or not c_tgt:
        return out

    for _, row in df.iterrows():
        try:
            prov_raw = row[c_prov]
            if pd.isna(prov_raw):
                continue
            prov = str(prov_raw).strip().upper()
            if _province_excluded(prov):
                continue
            art = row[c_art]
            if pd.isna(art) or not str(art).strip():
                continue
            articolo = str(art).strip()
            if is_pivot_aggregate_product_name(articolo):
                continue
            anno = int(float(row[c_anno]))
            mese = int(float(row[c_mese]))
            if not (1 <= mese <= 12) or not (2018 <= anno <= 2035):
                continue
        except (TypeError, ValueError, KeyError):
            continue

        tv = row[c_tgt]
        if not _is_numeric_measure_cell(tv) or float(tv) <= 0:
            continue

        cod_s: str | None = None
        if c_cod is not None and pd.notna(row[c_cod]):
            t = str(row[c_cod]).strip()
            cod_s = t if t else None

        k = (articolo.strip().upper(), prov, anno, mese)
        out[k] = {
            "cod": cod_s,
            "articolo": articolo,
            "year": anno,
            "month": mese,
            "prov": prov,
            "pieces": float(tv),
        }
    return out


def _merge_optional_targets_sheet(
    path: Path, targets_by_key: dict[tuple[str, str, int, int], dict[str, Any]]
) -> None:
    """Se esiste un foglio ``TARGET``, unisce/sovrascrive i target (griglia senza vendite)."""
    try:
        xlb = pd.ExcelFile(path)
    except Exception:
        return
    sheet_name = None
    for sn in xlb.sheet_names:
        if str(sn).strip().upper() == "TARGET":
            sheet_name = sn
            break
    if sheet_name is None or sheet_name == "DATABASE":
        return
    try:
        dft = pd.read_excel(path, sheet_name=sheet_name, header=0)
    except Exception:
        return
    extra = _parse_database_target_only_dataframe(dft)
    targets_by_key.update(extra)


def parse_database_workbook(
    path: str | Path,
) -> tuple[list[Row], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Foglio **DATABASE**: colonne tipiche ``COD``, ``ARTICOLO``, ``PROV``, ``ANNO``, ``MESE``,
    ``PEZZI``, ``FATTURATO``, ``TARGET`` (prima riga = header).

    Ritorna ``(fact_rows, target_rows, product_rows)`` per ``fact_measure``, ``target``, ``products``.
    Righe con ``TARGET`` > 0 sono importate anche se PEZZI/FATTURATO sono vuoti.
    Foglio opzionale **TARGET** (stesso file): stesse colonni chiave + TARGET; sovrascrive
    duplicati da DATABASE. Province **ONLINE** consentita; CO/CR escluse.
    """
    path = Path(path)
    facts: list[Row] = []
    targets_by_key: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    products: list[dict[str, Any]] = []

    df = pd.read_excel(path, sheet_name="DATABASE", header=0)
    colmap = {re.sub(r"\s+", "_", str(c).strip().upper()): c for c in df.columns}

    def col(*names: str):
        for n in names:
            k = re.sub(r"\s+", "_", n.strip().upper())
            if k in colmap:
                return colmap[k]
        return None

    c_cod = col("COD", "CODICE", "CODE")
    c_art = col("ARTICOLO", "PRODOTTO", "ART")
    c_prov = col("PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    c_anno = col("ANNO", "ANO", "YEAR")
    c_mese = col("MESE", "MONTH", "M", "NUM_MESE")
    c_pezzi = col("PEZZI", "QTA", "QUANTITA", "PIECES", "QIMS")
    c_fat = col("FATTURATO", "VALORE", "IMPORTO", "REVENUE", "VALUE", "FAT")
    c_tgt = col(
        "TARGET", "TARGET_PEZZI", "TARGET_QTY", "TARGET_QIMS", "PEZZI_TARGET"
    )

    if not c_art or not c_prov or not c_anno or not c_mese:
        return facts, [], products

    for _, row in df.iterrows():
        try:
            prov_raw = row[c_prov]
            if pd.isna(prov_raw):
                continue
            prov = str(prov_raw).strip().upper()
            if _province_excluded(prov):
                continue
            art = row[c_art]
            if pd.isna(art) or not str(art).strip():
                continue
            articolo = str(art).strip()
            if is_pivot_aggregate_product_name(articolo):
                continue
            anno = int(float(row[c_anno]))
            mese = int(float(row[c_mese]))
            if not (1 <= mese <= 12) or not (2018 <= anno <= 2035):
                continue
        except (TypeError, ValueError, KeyError):
            continue

        cod_s: str | None = None
        if c_cod is not None and pd.notna(row[c_cod]):
            t = str(row[c_cod]).strip()
            cod_s = t if t else None

        if c_pezzi is not None:
            qv = row[c_pezzi]
            if _is_numeric_measure_cell(qv):
                facts.append(
                    _row(
                        "DATABASE",
                        "pieces",
                        float(qv),
                        geo_code=prov,
                        hierarchy_level="product",
                        product_name=articolo,
                        product_cod=cod_s,
                        year=anno,
                        month=mese,
                    )
                )
        if c_fat is not None:
            fv = row[c_fat]
            if _is_numeric_measure_cell(fv):
                facts.append(
                    _row(
                        "DATABASE",
                        "revenue",
                        float(fv),
                        geo_code=prov,
                        hierarchy_level="product",
                        product_name=articolo,
                        product_cod=cod_s,
                        year=anno,
                        month=mese,
                    )
                )
        if c_tgt is not None:
            tv = row[c_tgt]
            if _is_numeric_measure_cell(tv) and float(tv) > 0:
                k = (articolo.strip().upper(), prov, anno, mese)
                targets_by_key[k] = {
                    "cod": cod_s,
                    "articolo": articolo,
                    "year": anno,
                    "month": mese,
                    "prov": prov,
                    "pieces": float(tv),
                }

    _merge_optional_targets_sheet(path, targets_by_key)
    targets = sorted(
        targets_by_key.values(),
        key=lambda t: (t["year"], t["month"], t["prov"], t["articolo"]),
    )

    try:
        xlb = pd.ExcelFile(path)
        if "ARTICOLI" in xlb.sheet_names:
            dfa = pd.read_excel(path, sheet_name="ARTICOLI", header=0)
            cmap = {str(c).strip().upper(): c for c in dfa.columns}
            ca = cmap.get("ARTICOLO") or cmap.get("PRODOTTO")
            cp = cmap.get("PREZZO") or cmap.get("PREZZO_IMS") or cmap.get("PRICE")
            cc = cmap.get("COD") or cmap.get("CODICE")
            if ca and cp:
                for _, row in dfa.iterrows():
                    an = row[ca]
                    if pd.isna(an) or not str(an).strip():
                        continue
                    articolo = str(an).strip()
                    pv = row[cp]
                    if not _is_numeric_measure_cell(pv):
                        continue
                    cod_p: str | None = None
                    if cc is not None and pd.notna(row[cc]):
                        t = str(row[cc]).strip()
                        cod_p = t if t else None
                    products.append(
                        {"cod": cod_p, "articolo": articolo, "prezzo": float(pv)}
                    )
    except Exception:
        pass

    return facts, targets, products


def iter_rows_from_xlsx(
    path: str | Path, *, skip_sheets: frozenset[str] | None = None
) -> Iterator[Row]:
    path = Path(path)
    skip = skip_sheets or frozenset()
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        if sheet in (SHEET_DB_SALES, SHEET_VENDITE_SEMI, SHEET_PHARMACIES):
            continue
        df = pd.read_excel(path, sheet_name=sheet, header=None)
        if sheet == "2025":
            yield from parse_sheet_monthly_province_product(
                df, sheet_code="2025", year=2025, max_months=10, include_fat=True
            )
        elif re.fullmatch(r"20\d{2}", str(sheet).strip()):
            y = int(str(sheet).strip())
            sc = str(sheet).strip()
            if _find_header_row(df) is not None:
                yield from parse_sheet_monthly_province_product(
                    df, sheet_code=sc, year=y, max_months=None, include_fat=True
                )
            else:
                yield from parse_sheet_pivot_province_product_pairs(
                    df, sheet_code=sc, year=y
                )
        elif sheet == "CR-CO":
            yield from parse_sheet_monthly_province_product(
                df, sheet_code="CR-CO", year=2025, max_months=12, include_fat=False
            )
        elif sheet == "ZIDOVAL 2025":
            yield from parse_sheet_zidoval(df)
        elif sheet == "ONLINE":
            if "ONLINE" not in skip:
                yield from parse_sheet_online(df)
        elif sheet == "SEDRAN":
            hr = _find_header_row(df)
            # Layout DEF (target 2026) → solo tabelle target/prezzi, non fact_measure
            if hr == 6 and df.shape[1] >= 15:
                continue
            if df.shape[1] >= 9:
                yield from parse_sheet_sedran_pivot(df, year=2025)
        elif sheet == SHEET_VENDITE_SEMI:
            continue
        elif sheet == SHEET_MANUAL_TARGET_PREZZI:
            continue
