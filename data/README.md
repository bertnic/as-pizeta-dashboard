# Dashboard `data/`: parser e caricamento mart

### Database

Un solo file: **`{DATA_DIR}/pizeta.sqlite`**, come **`db_store`** in Flask: se **`DATA_DIR`** non è nell’ambiente, viene **impostata nel codice** a **`mono/var`** quando esegui sotto il mono; altrimenti va impostata a mano. Catalogo prodotti = **`products.catalog_id`** (nessuna tabella **`import_batch`** nel DB). DDL mart: **`packages/db/migrations/002_pharma_datamart.sql`** (mirror **`schema.sql`**).

### Workbook IMS (default mono)

- **`mono/datalake/DATABASE.xlsx`** (path canonico)

Override: **`PIZETA_DATABASE_XLSX`** o **`--xlsx`** su **`etl_build_db.py`**.

### Opzionale: Excel → `pizeta.sqlite`

```bash
cd apps/dashboard/data/
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-etl.txt
# stesso DATA_DIR di Flask (default mono/var):
python3 etl_build_db.py
```

Da mono, senza env: output = **`mono/var/pizeta.sqlite`**, input = **`datalake/DATABASE.xlsx`**. Convieni **`packages/db/scripts/migrate.py --db …/pizeta.sqlite`** prima del primo run se servono **`users`** e tabelle platform.

**`parsers.py`**: parsing fogli / PDF.

| File | Ruolo |
|------|--------|
| `etl_build_db.py` | Carica workbook → mart in **`DATA_DIR/pizeta.sqlite`** |
| `parsers.py` | Parsing |
| `sync_from_google.py` | Drive (gitignored credenziali) |

### Reference CSV (Strame)

Tipicamente fuori repo, es. `…/strame/user_stories/`:

| Path (tipico) | Uso |
|---------------|-----|
| `…/PRODOTTI/Prodotti.csv` | **`load_reference_csv.py --prodotti`** |
| `…/MEDICI/HCP.csv` | Futuro |
| `…/STRUTTURE/Strutture.csv` | Futuro |

Il **dashboard React** usa **`/api/datamart/summary`** su **`pizeta.sqlite`**.
