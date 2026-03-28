# as-pizeta-dashboard

A full-stack project utilizing React (Vite) and Python (Flask) for tracking and visualizing Pharma Analytics.
The backend relies on Google OAuth for authentication, issues a 2FA token using TOTP logic, and relies on `pdfplumber` for scraping and persisting sales data.

**Layout:** `app/backend/` (Flask), `app/frontend/` (Vite/React). Build the container from this repository root (`docker build` / `podman build` context = `.`).

## Usage

1. Authenticate using Google OAuth
2. Enter the 2FA Code
3. View existing entries or supply new Sales PDF data.

## Deployment

- **Google Cloud Run:** see [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md).
- **Podman + Nginx (VM):** follow the sections below.

---

## Podman deployment (VM)

### Architettura

```
Internet → Nginx (443/SSL) → Podman Container (porta 8080, Flask+React)
                           ↓
                     /data (volume persistente: utenti, dati PDF)
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
5. Il dataset viene persistito in `/data/pharma_data.json`

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

---

### Struttura file nel container

```
/app/
  app.py              ← Backend Flask
  frontend/dist/      ← React compilato
/data/
  users.json          ← Utenti e segreti TOTP
  pharma_data.json    ← Dati PDF caricati
```
