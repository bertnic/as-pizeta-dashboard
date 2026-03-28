# Pharma datamart (ETL)

This folder holds the **analytics SQLite pipeline**: Excel/PDF → **`pharma_datamart.sqlite`** with star-schema tables (`import_batch`, `fact_measure`, `TARGET`, `PRODOTTI`, `FATTURATO`).

It is **separate** from the Flask app runtime DB **`pizeta.sqlite`** (users + PDF uploads as JSON), which lives under `DATA_DIR` / `var/` — see the repository root `README.md`.

## Bringing your existing tree from `~/Development/projects/as/pizeta/dashboard/data`

1. **Copy or symlink** into this directory (same repo path: `apps/dashboard/data/` when using mono):
   - `pharma_datamart.sqlite` (optional if you will rebuild from sources)
   - Canonical workbooks (e.g. `SEDRAN*.xlsx`) and PDFs the parsers expect  
2. Or **only** copy the sources and rebuild:
   ```bash
   cd apps/dashboard/data   # from mono: mono/apps/dashboard/data
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-etl.txt
   python3 etl_build_db.py --db ./pharma_datamart.sqlite
   ```
   Add `--all-xlsx` / `--append` per `etl_build_db.py --help`.

## Schema source of truth

- Mono: **`packages/db/migrations/002_pharma_datamart.sql`**
- ETL uses that file automatically when the repo is checked out under `mono/`; otherwise it uses **`schema.sql`** here.
- Override: `export DATAMART_SCHEMA_SQL=/path/to/002_pharma_datamart.sql`

## Scripts

| File | Role |
|------|------|
| `etl_build_db.py` | Create DB, apply schema, load xlsx/pdf from this directory |
| `parsers.py` | Sheet/PDF parsing |
| `verify_pivots.py` | Sanity checks on `pharma_datamart.sqlite` |
| `sync_from_google.py` | Drive download (needs `credentials.json` / OAuth token — gitignored) |

## Next step for the product

The **React dashboard** does not yet read `pharma_datamart.sqlite`; it still uses embedded demo data + `pizeta.sqlite` uploads. Wiring API routes to query the datamart (read-only) is a follow-up task.
