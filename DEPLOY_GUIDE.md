# PharmaAnalytics Dashboard – Deployment Guide (Google Cloud Run)

## Architettura Serverless

```
Internet → Google Cloud Run (Custom Domain as.bertellini.org)
                           ↓
                  GCS FUSE (Volume persistente: utenti, dati PDF)
```

Il progetto gira su **Google Cloud Run** in modalità serverless. Non richiede gestione del server, VM o Nginx manuale. Il container scale a zero quando inattivo.

---

## 1. Prerequisiti & Setup Iniziale

I comandi seguenti presuppongono che tu abbia installato la `gcloud` CLI e autenticato l'account tramite `gcloud auth login`.

```bash
# Sostituisci con il tuo Project ID
export PROJECT_ID="TUO-PROJECT-ID"
gcloud config set project $PROJECT_ID

# Abilita le API necessarie
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  cloudbuild.googleapis.com
```

---

## 2. Google OAuth – Configurazione

1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un progetto → API e servizi → Credenziali
3. Crea **OAuth 2.0 Client ID** (tipo: Web application)
4. Aggiungi **Authorized redirect URIs**:
   ```
   https://as.bertellini.org/pizeta/dashboard/auth/callback
   ```
5. Salva `Client ID` e `Client Secret` per lo step 4.

---

## 3. Creazione Bucket (Persistenza Dati)

Dato che Cloud Run è stateless, usiamo **Google Cloud Storage FUSE** per montare la directory `/data` del container come volume.

```bash
export BUCKET_NAME="as-pizeta-dashboard-data"

# Crea il bucket in europa (es. europe-west1 o europe-south1)
gcloud storage buckets create gs://$BUCKET_NAME --location=europe-west1

# Ottieni l'account di servizio di default per il Compute Engine
export PROJECT_NUM=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
export SVC_ACCOUNT="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

# Assegna i permessi per leggere e scrivere nel bucket
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SVC_ACCOUNT" \
  --role="roles/storage.objectAdmin"
```

---

## 4. Build e Deploy su Cloud Run

Entra nella directory del container, `pharma-dashboard`, e usa il comando deploy integrato. Google Cloud CLI utilizzerà Cloud Build per impacchettare il Dockerfile in remoto ed avviare il servizio.

```bash
cd ./pharma-dashboard

# Definisci le variabili sensibili
export GOOGLE_CLIENT_ID="IL_TUO_CLIENT_ID"
export GOOGLE_CLIENT_SECRET="IL_TUO_CLIENT_SECRET"
export SECRET_KEY="$(openssl rand -hex 32)"

# Deploy su Cloud Run
gcloud run deploy pharma-dashboard \
  --source . \
  --region europe-west1 \
  --execution-environment gen2 \
  --add-volume=name=bucket-vol,type=cloud-storage,bucket=$BUCKET_NAME \
  --add-volume-mount=volume=bucket-vol,mount-path=/data \
  --set-env-vars="GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID},GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET},SECRET_KEY=${SECRET_KEY}" \
  --allow-unauthenticated
```

---

## 5. Mappatura Dominio Custom (`as.bertellini.org`)

Per puntare il tuo dominio personalizzato direttamente a Cloud Run:

```bash
gcloud beta run domain-mappings create \
  --service=pharma-dashboard \
  --domain=as.bertellini.org \
  --region=europe-west1
```

L'output del terminale ti indicherà le modifiche da applicare ai record DNS su **Cloudflare**.

### Configurazione su Cloudflare:
1. Vai su **DNS** > **Records**.
2. Aggiungi i record `CNAME` o `A / AAAA` per il dominio `as` (`as.bertellini.org`) forniti da Google.
3. Imposta **Proxy status** a **DNS Only** finché i certificati SSL generati da Google (Managed SSL) non saranno operativi.
4. Una volta che Cloud Run risulterà associato, l'app sarà perfettamente accessibile a:
   👉 `https://as.bertellini.org/pizeta/dashboard`

---

## Note Aggiuntive e Costi

- **Costi Server**: L'ambiente Free Tier copre milioni di richieste al mese, portando di fatto il costo per traffico limitato a `€0/mese`.
- **Primo Accesso (2FA)**: Al primo login verrà generato un QR Code TOTP (da scannerizzare tramite Google Authenticator, Authy o simili). Successivamente ti verrà chiesta l'OTP ad ogni nuovo accesso.
- **Aggiornamento App**: Per applicare modifiche a Vue/Flask in futuro, sarà sufficiente usare di nuovo `gcloud run deploy --source .` dalla cartella di progetto. Cloud Build aggiornerà automaticamente l'ultima revisione in zero-downtime.
