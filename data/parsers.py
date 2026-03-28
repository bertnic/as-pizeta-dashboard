"""
Extract normalized measure rows from SEDRAN-style Excel sheets and monthly PDF reports.

Semantiche (allineamento business):
- Foglio **2025**: integratori — colonne D–M (0-based 3–12) = pezzi (QIMS) mesi 1–10;
  N–W = fatturato (Fat IMS) mesi 1–10.
- **ZIDOVAL 2025**: farmaco — solo pezzi per area/regione e mese.
- **SEDRAN** (non DEF): mesi 10–12 — coppie (C,D), (E,F), (G,H) in 1-based Excel =
  pezzi e fatturato; righe agente/provincia (totali parziali) non vanno in fact_measure.
- **PDF**: stessa logica del foglio 2025 (10+10 valori + totali riga).
- Province **CO** e **CR** escluse ovunque; foglio **CR-CO** importato ma righe su quelle sigle scartate.

Used by etl_build_db.py and verify_pivots.py.
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

# Foglio manuale: TARGET + PREZZI/PRODOTTI (e opz. FATTURATO) in blocchi con titolo in colonna A
SHEET_MANUAL_TARGET_PREZZI = "1TQAGiWBTbYf9IPUqrhS9DBv5WFftDPqI"

# Legacy: solo righe tipo fatturato → tabella FATTURATO (anno default se mancante)
SHEET_VENDITE_SEMI = "1W7R3_Few1FfqUgBzm2ep3AKRqBNyl6E2"

# Workbook canonico consigliato (altri SEDRAN (*.xlsx) sono duplicati)
CANONICAL_XLSX_NAMES = frozenset({"SEDRAN (1).xlsx", "SEDRAN DEF..xlsx"})


def _province_excluded(code: str | None) -> bool:
    if code is None:
        return False
    s = str(code).strip().upper()
    return s in EXCLUDED_PROVINCE_CODES


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
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
) -> Row:
    return {
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


def _find_header_row(df: pd.DataFrame, marker: str = "kProvincia") -> int | None:
    for r in range(min(30, len(df))):
        v = df.iat[r, 1]
        if isinstance(v, str) and v.strip() == marker:
            return r
    return None


def parse_sheet_monthly_province_product(
    df: pd.DataFrame,
    *,
    sheet_code: str,
    year: int,
    max_months: int = 10,
    include_fat: bool = True,
) -> list[Row]:
    """
    Sheets '2025' and 'CR-CO': kProvincia | Articolo | QIMS m1..mN | [FatIMS m1..mN] | [row totals].
    """
    out: list[Row] = []
    hr = _find_header_row(df)
    if hr is None:
        return out

    n_months = max_months
    last_q = 2 + n_months  # exclusive end col for QIMS (col 2 = Articolo)
    last_f = last_q + n_months if include_fat else None
    if df.shape[1] < (last_f or last_q) + 1:
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

        for mi in range(n_months):
            qv = df.iat[r, 3 + mi]
            if pd.notna(qv) and isinstance(qv, (int, float)):
                out.append(
                    _row(
                        sheet_code,
                        "qims",
                        float(qv),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=mi + 1,
                    )
                )
        if include_fat and last_f is not None:
            for mi in range(n_months):
                fv = df.iat[r, last_q + mi]
                if pd.notna(fv) and isinstance(fv, (int, float)):
                    out.append(
                        _row(
                            sheet_code,
                            "fat_ims",
                            float(fv),
                            geo_code=current_province,
                            hierarchy_level="product",
                            product_name=product,
                            year=year,
                            month=mi + 1,
                        )
                    )
            tq = df.iat[r, last_f]
            tf = df.iat[r, last_f + 1] if df.shape[1] > last_f + 1 else None
            if pd.notna(tq) and isinstance(tq, (int, float)):
                out.append(
                    _row(
                        sheet_code,
                        "row_total_qims",
                        float(tq),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=0,
                    )
                )
            if pd.notna(tf) and isinstance(tf, (int, float)):
                out.append(
                    _row(
                        sheet_code,
                        "row_total_fat",
                        float(tf),
                        geo_code=current_province,
                        hierarchy_level="product",
                        product_name=product,
                        year=year,
                        month=0,
                    )
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
                        "zidoval_units",
                        float(v),
                        geo_label=label,
                        hierarchy_level="na",
                        year=y,
                        month=m,
                    )
                )
    return out


def parse_sheet_online(df: pd.DataFrame) -> list[Row]:
    out: list[Row] = []
    header_r: int | None = None
    for r in range(min(15, len(df))):
        row_vals = [df.iat[r, c] for c in range(min(8, df.shape[1]))]
        joined = " ".join(str(x) for x in row_vals if pd.notna(x))
        if "Order Date" in joined and "Item Name" in joined:
            header_r = r
            break
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
                        "quantity",
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
                        "net",
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
                            "qims",
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
                            "fat_ims",
                            float(f),
                            geo_code=geo,
                            agent_name=agent,
                            hierarchy_level=level,
                            product_name=prod,
                            year=year,
                            month=m,
                        )
                    )
            tq, tf = df.iat[r, 8], df.iat[r, 9]
            if pd.notna(tq) and isinstance(tq, (int, float)):
                out.append(
                    _row(
                        "SEDRAN",
                        "row_total_qims",
                        float(tq),
                        geo_code=geo,
                        agent_name=agent,
                        hierarchy_level=level,
                        product_name=prod,
                        year=year,
                        month=0,
                    )
                )
            if pd.notna(tf) and isinstance(tf, (int, float)):
                out.append(
                    _row(
                        "SEDRAN",
                        "row_total_fat",
                        float(tf),
                        geo_code=geo,
                        agent_name=agent,
                        hierarchy_level=level,
                        product_name=prod,
                        year=year,
                        month=0,
                    )
                )

        has_any_measure = any(
            pd.notna(x) and isinstance(x, (int, float)) for x in (c2, c3, c4, c5, c6, c7)
        )
        if not has_any_measure:
            continue

        if _is_province_code(label_s):
            current_province = label_s
            continue

        if current_province and not _province_excluded(current_province):
            prod = label_s
            emit_pairs(geo=current_province, agent=None, level="product", prod=prod)
            continue

        # Riga agente / totali parziali iniziali: non persistiamo (solo contesto)
        if "SEDRAN" in label_s.upper():
            current_province = None
    return out


def parse_sedran_def_targets_prezzi(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    SEDRAN DEF → target premio produzione: TARGET(prov, articolo, anno, mese, pezzi) e PREZZI(articolo, prezzo).
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
            months.append((dt.year, dt.month))
        else:
            try:
                p = pd.to_datetime(dt)
                months.append((int(p.year), int(p.month)))
            except Exception:
                break

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
                        "anno": int(y),
                        "mese": int(m),
                        "qta": float(v),
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


def read_sedran_def_sheet(path: Path) -> pd.DataFrame | None:
    if not is_sedran_def_workbook(path):
        return None
    xl = pd.ExcelFile(path)
    if "SEDRAN" not in xl.sheet_names:
        return None
    return pd.read_excel(path, sheet_name="SEDRAN", header=None)


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
                        "anno": anno,
                        "mese": mese,
                        "prov": prov_s,
                        "qta": qta_v,
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
                        "anno": anno,
                        "mese": mese,
                        "prov": prov_s or None,
                        "qta": qta_v,
                        "valore": valore,
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
    Normalizza il foglio semi-strutturato a: cod, articolo, prov, mese, qta, valore.
    Province CO/CR escluse.
    """
    if df is None or df.empty:
        return []

    cod_c = _pick_col(df, "COD", "CODICE", "ID", "CODE")
    art_c = _pick_col(df, "ARTICOLO", "PRODOTTO", "ART")
    prov_c = _pick_col(df, "PROV", "PROVINCIA", "SIGLA", "KPROVINCIA")
    mes_c = _pick_col(df, "MESE", "MONTH", "NUM_MESE", "M")
    qta_c = _pick_col(df, "QTA", "QUANTITA", "QT", "PEZZI", "QIMS")
    val_c = _pick_col(df, "VALORE", "IMPORTO", "TOTALE", "FATTURATO", "NETTO", "TOT_NETTO")
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
                "anno": anno,
                "mese": mese,
                "prov": prov,
                "qta": qta,
                "valore": valore,
            }
        )
    return out


def iter_vendite_semi_rows(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    xl = pd.ExcelFile(path)
    if SHEET_VENDITE_SEMI not in xl.sheet_names:
        return []
    df = pd.read_excel(path, sheet_name=SHEET_VENDITE_SEMI, header=0)
    return parse_sheet_vendite_semi(df)


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
    if not product:
        return None

    row_tot_fat = nums[-1]
    row_tot_qims = nums[-2]
    fat_vals = nums[-12:-2]
    qims_vals = nums[:-12]

    if len(qims_vals) != 10 or len(fat_vals) != 10:
        return None

    out: list[Row] = []
    for mi, q in enumerate(qims_vals):
        out.append(
            _row(
                "PDF_MONTHLY",
                "qims",
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
                "fat_ims",
                f,
                geo_code=province,
                hierarchy_level="product",
                product_name=product,
                year=2025,
                month=mi + 1,
            )
        )
    out.append(
        _row(
            "PDF_MONTHLY",
            "row_total_qims",
            row_tot_qims,
            geo_code=province,
            hierarchy_level="product",
            product_name=product,
            year=2025,
            month=0,
        )
    )
    out.append(
        _row(
            "PDF_MONTHLY",
            "row_total_fat",
            row_tot_fat,
            geo_code=province,
            hierarchy_level="product",
            product_name=product,
            year=2025,
            month=0,
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


def iter_rows_from_xlsx(path: str | Path) -> Iterator[Row]:
    path = Path(path)
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=None)
        if sheet == "2025":
            yield from parse_sheet_monthly_province_product(
                df, sheet_code="2025", year=2025, max_months=10, include_fat=True
            )
        elif sheet == "CR-CO":
            yield from parse_sheet_monthly_province_product(
                df, sheet_code="CR-CO", year=2025, max_months=12, include_fat=False
            )
        elif sheet == "ZIDOVAL 2025":
            yield from parse_sheet_zidoval(df)
        elif sheet == "ONLINE":
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
