# as-pizeta-dashboard

A full-stack project utilizing React (Vite) and Python (Flask) for tracking and visualizing Pharma Analytics.
The backend relies on Google OAuth for authentication and issues a 2FA token using TOTP logic. **IMS / mart data** lives in **`pizeta.sqlite`** (see `packages/db/`); optional Excel loader in **`data/etl_build_db.py`**. The dashboard UI does **not** upload PDFs.

**Layout:** `app/backend/` (Flask), `app/frontend/` (Vite/React). Build the container from this repository root (`docker build` / `podman build` context = `.`).

**Local dev:** from `app/frontend/` run `npm install` and `npm run dev` (Vite proxies `/pizeta/dashboard/...` to Flask on **8080**). From `app/backend/` install `requirements.txt`, then run `python app.py` on **8080**.

- **Quick UI test (no Google OAuth):** `AUTH_MODE=development python app.py` — session is auto-authenticated; **`GOOGLE_*`** vars optional. Use only on localhost; never in production.
- **Real auth:** set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `SECRET_KEY`; do **not** set `AUTH_MODE=development`.
- **Cookies on HTTP:** without Cloud Run’s `K_SERVICE`, `SESSION_COOKIE_SECURE` defaults to **false** so the session works on `http://127.0.0.1`. Override with `SESSION_COOKIE_SECURE=true` if you terminate TLS locally.

**Tests:** from repo root, `pip install -r requirements-dev.txt` then `pytest tests/`.

### Local database (SQLite) — what exists?

- **The file is not in Git.** `pizeta.sqlite` appears on disk after the backend has run and touched the DB (e.g. first OAuth flow or `/api/datamart/summary`).
- **Location (shared platform DB, all apps):** sempre **`DATA_DIR/pizeta.sqlite`**. Se **`DATA_DIR`** non è nell’ambiente, il backend la **imposta nel codice** a **`mono/var`** (path assoluto) quando gira sotto il mono; fuori mono va impostata esplicitamente (Docker/Cloud Run: **`DATA_DIR=/data`** nel Dockerfile).  
  - **Local mono:** no env required — run Flask from `app/backend/` and the file is created under **`../../var/`** relative to the submodule root (i.e. **`mono/var/pizeta.sqlite`**).  
  - **Containers / Cloud Run:** volume on **`/data`**; **`DATA_DIR=/data`** is set in the Dockerfile.
    ```bash
    cd app/backend && python dev_db_status.py   # shows resolved path and row counts
    ```
- **Tables** (created automatically from schema on first use):

| Table | Purpose |
|-------|--------|
| `users` | One row per Google user who has signed in; TOTP secret and profile (`display_name`, `picture_url`). |

- **Row counts:** `users` stays `0` until someone logs in (unless legacy `users.json` was imported). Mart tables are filled by **`migrate.py`**, manual load, or optionally **`data/etl_build_db.py`** (scrive in **`pizeta.sqlite`**), not by the dashboard UI.

**Schema:** On first backend access, **`db_store`** applies **`001_dashboard_app.sql`**, **`003_platform_new_tables.sql`**, and **`004_drop_dashboard_upload.sql`** (or resolves the same files from **`mono/packages/db/migrations/`** when the app sits under the mono tree). Se manca il mart, applica anche **`002`**. DDL completo (**`001`–`004`** + mart) con **`python3 packages/db/scripts/migrate.py --db "$DATA_DIR/pizeta.sqlite"`** dal mono — vedi **`packages/db/README.md`**.

**Restoring legacy `users.json`:** Copy **`users.json`** next to **`pizeta.sqlite`** and start the app once (imports only when **`users`** is empty), or run from **`app/backend/`**:

```bash
export DATA_DIR=/path/to/folder/with/json/files
python3 import_legacy_dashboard_json.py --db "$DATA_DIR/pizeta.sqlite"
# DB already has rows but JSON should add missing emails:
python3 import_legacy_dashboard_json.py --db "$DATA_DIR/pizeta.sqlite" --merge-users
```

**Platform evolution (single `pizeta.sqlite`, `users` / `sales` / `products`, Strame & Notaspese tables):** mono **`packages/db/plans/unified-pizeta-sqlite.md`**.

### Mart IMS (stesso file dell’app)

Schema mart: **`packages/db/migrations/002_pharma_datamart.sql`**. Opzionale: da **`data/`**, **`etl_build_db.py`** usa **`DATA_DIR`** come Flask e legge **`mono/datalake/DATABASE.xlsx`** (path canonico). Esegui prima **`migrate.py`** sullo stesso **`pizeta.sqlite`** se serve schema platform. Dettagli: **[data/README.md](data/README.md)**.

**Bootstrap** (schema + `users.json` opzionale): **`packages/db/scripts/bootstrap_pizeta.py`** — vedi **`packages/db/README.md`**.

**`/api/datamart/summary`** aggrega solo **`sales`** (con join **`products`**) e **`target`**; non usa `fact_measure`.

**Product catalog (Strame):** path `…/strame/user_stories/PRODOTTI/Prodotti.csv` — load into SQLite with **`packages/db/scripts/load_reference_csv.py --prodotti`** (see **`data/README.md`**).

## Usage

1. Authenticate using Google OAuth
2. Enter the 2FA Code
3. View analytics from the mart in **`pizeta.sqlite`** (data refresh outside this UI).

## Deployment

- **Google Cloud Run:** [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md) (only Cloud Run; build context = repo root).
- **Podman + Nginx (VM):** sections below (same `Dockerfile` at repo root).

---

## Podman deployment (VM)

### Architettura

```
Internet → Nginx (443/SSL) → Podman Container (porta 8080, Flask+React)
                           ↓
                     /data (volume persistente: pizeta.sqlite)
```

Il container gira in rete `host` per coesistere con WireGuard senza conflitti.

L'immagine espone **8080** di default (`PORT` override supportato). Nginx deve fare proxy verso quella porta.

---

### 1. Prerequisiti sul server (f1-micro, Debian/Ubuntu)

```bash
# Installa Podman se non presente
sudo apt-get install -y podman

# Installa Nginx
sudo apt-get install -y nginx

# Installa Certbot per SSL Let's Encrypt
sudo apt-get install -y certbot python3-certbot-nginx
```

---

### 2. Google OAuth – Configurazione

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un progetto → API e servizi → Credenziali
3. Crea **OAuth 2.0 Client ID** (tipo: Web application)
4. Aggiungi **Authorized redirect URIs**:
   ```
   https://TUO-DOMINIO/auth/callback
   ```
5. Salva `Client ID` e `Client Secret`

---

### 3. Build e avvio del container

```bash
# Sul server, clona/copia il progetto
cd /opt/as-pizeta-dashboard

# Build immagine (contesto = root del repo)
podman build -t as-pizeta-dashboard:latest .

# Crea directory dati persistente
sudo mkdir -p /opt/pharma-data
sudo chown 1001:1001 /opt/pharma-data

# Avvio container
podman run -d \
  --name as-pizeta-dashboard \
  --restart=always \
  -p 127.0.0.1:8080:8080 \
  -v /opt/pharma-data:/data:Z \
  -e GOOGLE_CLIENT_ID="IL_TUO_CLIENT_ID" \
  -e GOOGLE_CLIENT_SECRET="IL_TUO_CLIENT_SECRET" \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  as-pizeta-dashboard:latest
```

> **Nota**: usa `-p 127.0.0.1:8080:8080` così l'app è accessibile solo da Nginx (non esposta pubblicamente). Per una porta diversa imposta anche `-e PORT=...` coerente.

---

### 4. Systemd service per Podman (auto-start)

```bash
# Genera il service file
podman generate systemd --new --name as-pizeta-dashboard \
  > /etc/systemd/system/as-pizeta-dashboard.service

sudo systemctl daemon-reload
sudo systemctl enable --now as-pizeta-dashboard
```

---

### 5. Nginx + SSL

```bash
# Ottieni certificato SSL
sudo certbot --nginx -d TUO-DOMINIO.com

# Copia la configurazione Nginx (se presente nel repo, es. nginx/pharma.conf)
sudo cp nginx/pharma.conf /etc/nginx/sites-available/pharma
sudo ln -s /etc/nginx/sites-available/pharma /etc/nginx/sites-enabled/

# Aggiorna il server_name nella configurazione
sudo sed -i 's/server_name _;/server_name TUO-DOMINIO.com;/' \
  /etc/nginx/sites-available/pharma

# Test e reload
sudo nginx -t && sudo systemctl reload nginx
```

Aggiorna il blocco `proxy_pass` in Nginx in modo che punti a `http://127.0.0.1:8080` (o alla porta che usi con `PORT`).

---

### 6. Coesistenza con WireGuard

WireGuard usa `wg0` (tipicamente `10.x.x.x`). Il container Flask è solo su `127.0.0.1:8080` quindi non ci sono conflitti. Se WireGuard è su `51820/udp` e Nginx su `443/tcp`, non ci sono collisioni di porte.

Verifica firewall:

```bash
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp
# Non aprire la porta dell'app – rimane interna
```

---

### 7. Primo accesso e 2FA

1. Vai su `https://TUO-DOMINIO.com`
2. Clicca "Accedi con Google" → autenticati
3. Al primo accesso viene mostrato il QR code TOTP
4. Scansiona con **Google Authenticator**, **Authy**, o altra app TOTP
5. Inserisci il codice a 6 cifre → accesso completato

Da questo momento ogni login richiederà il codice TOTP dal telefono.

---

### 8. Caricamento mensile PDF

1. Accedi alla dashboard
2. Menu laterale → **"Carica PDF"**
3. Seleziona il PDF mensile nel formato QIMS
4. Il sistema estrae e aggiunge i dati ai grafici
5. Il dataset viene persistito nel database SQLite (`pizeta.sqlite` sotto **`DATA_DIR`**, es. **`/data`** nel container se così configurato)

---

### 9. Aggiornamento applicazione

```bash
cd /opt/as-pizeta-dashboard
git pull  # se versionato

# Rebuild
podman build -t as-pizeta-dashboard:latest .

# Restart
podman stop as-pizeta-dashboard
podman rm as-pizeta-dashboard
# Rilancia con il comando run del punto 3
sudo systemctl restart as-pizeta-dashboard
```

---

### 10. Backup dati

```bash
# Backup manuale
tar czf backup-$(date +%Y%m%d).tar.gz /opt/pharma-data/

# Cron giornaliero (opzionale)
echo "0 2 * * * root tar czf /backup/pharma-$(date +\%Y\%m\%d).tar.gz /opt/pharma-data/" \
  >> /etc/crontab
```

---

### Variabili d'ambiente richieste

| Variabile | Descrizione |
|-----------|-------------|
| `GOOGLE_CLIENT_ID` | OAuth Client ID da Google Cloud |
| `GOOGLE_CLIENT_SECRET` | OAuth Client Secret da Google Cloud |
| `SECRET_KEY` | Chiave casuale per le sessioni Flask (min 32 char) |
| `DATA_DIR` | Directory che contiene **`pizeta.sqlite`**. In mono, se assente viene impostata nel codice a **`mono/var`**; in container va impostata (es. **`/data`**) |
| `DASHBOARD_SCHEMA_SQL` | Percorso DDL personalizzato (opzionale; default file in `app/backend/` o mono `packages/db/migrations/`) |

---

### Struttura file nel container

```
/app/
  app.py              ← Backend Flask
  db_store.py         ← Accesso SQLite
  001_dashboard_app.sql
  003_platform_new_tables.sql
  004_drop_dashboard_upload.sql
  frontend/dist/      ← React compilato
/data/
  pizeta.sqlite       ← Utenti TOTP + mart (dopo migrate / import)
```
