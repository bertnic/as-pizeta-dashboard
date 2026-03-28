#!/usr/bin/env python3
"""
Sincronizza una cartella Google Drive nel progetto (API Google Drive v3).

Supporta:
  - File binari (PDF, .xlsx caricati come file, .xls, ecc.) → download diretto
  - Google Fogli → export come .xlsx
  - Google Documenti → export come PDF (lettura / archivio)

L’API Google Docs (documents.documents.get) serve a leggere il contenuto strutturato
del documento (JSON); per *scaricare* un file che vedi su Drive si usa l’export
tramite Drive API, che è quanto fa questo script.

Autenticazione (scegline una):

1) OAuth utente (consigliato in locale)
   - Google Cloud Console → API e servizi → Credenziali → Crea ID client OAuth
     → Applicazione desktop.
   - Scarica JSON e salvalo come:  data/credentials.json
   - Abilita nel progetto GCP: **Google Drive API** e **Google Docs API**.
   - Esegui:  python3 sync_from_google.py
   - Si apre il browser: accetta i permessi; viene creato data/token.json

2) Service account
   - Esporta la chiave JSON e:  export GOOGLE_APPLICATION_CREDENTIALS=/percorso/chiave.json
   - Condividi la cartella Drive con l’email del service account.
   - Esegui:  python3 sync_from_google.py --service-account

Cartella predefinita (progetto Pizeta):
  1tcAwqVhMZL3wALH2_4-H4754FoNwrNYn

Uso:
  cd data && pip install -r requirements-etl.txt
  python3 sync_from_google.py [--out DIR] [--folder FOLDER_ID]
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
from pathlib import Path

# Cartella condivisa (ID dalla URL Drive)
DEFAULT_FOLDER_ID = "1tcAwqVhMZL3wALH2_4-H4754FoNwrNYn"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

ROOT = Path(__file__).resolve().parent
CREDENTIALS_PATH = ROOT / "credentials.json"
TOKEN_PATH = ROOT / "token.json"

MIME_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_DOC = "application/vnd.google-apps.document"
MIME_FOLDER = "application/vnd.google-apps.folder"

EXPORT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_PDF = "application/pdf"


def _sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name or "unnamed"


def _get_credentials_oauth() -> object:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS_PATH.is_file():
        print(
            "Manca data/credentials.json (OAuth client Desktop da Google Cloud Console).",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = None
    if TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print(f"Token salvato in {TOKEN_PATH}")

    return creds


def _get_credentials_service_account() -> object:
    from google.oauth2 import service_account

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path or not Path(path).is_file():
        print(
            "Imposta GOOGLE_APPLICATION_CREDENTIALS sul file JSON del service account.",
            file=sys.stderr,
        )
        sys.exit(1)
    return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)


def _build_drive(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _build_docs(creds):
    from googleapiclient.discovery import build

    return build("docs", "v1", credentials=creds, cache_discovery=False)


def _docs_title(docs_service, document_id: str) -> str | None:
    """API Google Docs: metadati (titolo) del documento nativo."""
    try:
        doc = docs_service.documents().get(documentId=document_id).execute()
        return doc.get("title")
    except Exception:
        return None


def list_folder_files(service, folder_id: str) -> list[dict]:
    out: list[dict] = []
    page_token = None
    q = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, shortcutDetails)",
                pageToken=page_token,
                pageSize=100,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f.get("mimeType") == MIME_FOLDER:
                continue
            out.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def download_binary(service, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def export_file(service, file_id: str, mime: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().export_media(fileId=file_id, mimeType=mime)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def sync_folder(service, docs_service, folder_id: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = list_folder_files(service, folder_id)
    if not files:
        print("Nessun file nella cartella (o cartella vuota / permessi insufficienti).")
        return

    for f in files:
        fid = f["id"]
        name = f["name"]
        mime = f["mimeType"]
        shortcut = f.get("shortcutDetails") or {}
        if shortcut.get("targetId"):
            fid = shortcut["targetId"]
            # mimeType dello shortcut può essere fuorviante; ricarica metadata
            meta = service.files().get(fileId=fid, fields="id, name, mimeType").execute()
            name = meta.get("name", name)
            mime = meta.get("mimeType", mime)

        safe = _sanitize_filename(name)
        try:
            if mime == MIME_SHEET:
                data = export_file(service, fid, EXPORT_XLSX)
                if not safe.lower().endswith(".xlsx"):
                    safe = f"{safe}.xlsx"
                dest = out_dir / safe
                dest.write_bytes(data)
                print(f"  [Fogli→xlsx] {dest.name}")
            elif mime == MIME_DOC:
                title = _docs_title(docs_service, fid) if docs_service else None
                data = export_file(service, fid, EXPORT_PDF)
                base = safe.rsplit(".", 1)[0] if "." in safe else safe
                dest = out_dir / f"{base}.pdf"
                dest.write_bytes(data)
                extra = f' — Docs API titolo: "{title}"' if title else ""
                print(f"  [Documenti→pdf] {dest.name}{extra}")
            else:
                data = download_binary(service, fid)
                dest = out_dir / safe
                dest.write_bytes(data)
                print(f"  [download] {dest.name}")
        except Exception as e:
            print(f"  ERRORE {name}: {e}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync Google Drive folder → data/drive_import")
    ap.add_argument("--folder", default=DEFAULT_FOLDER_ID, help="ID cartella Drive")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "drive_import",
        help="Directory di destinazione",
    )
    ap.add_argument(
        "--service-account",
        action="store_true",
        help="Usa GOOGLE_APPLICATION_CREDENTIALS invece di OAuth",
    )
    args = ap.parse_args()

    if args.service_account:
        creds = _get_credentials_service_account()
    else:
        creds = _get_credentials_oauth()

    service = _build_drive(creds)
    docs_service = _build_docs(creds)
    print(f"Cartella Drive: {args.folder}")
    print(f"Destinazione:   {args.out.resolve()}")
    sync_folder(service, docs_service, args.folder, args.out)
    print("Fatto.")


if __name__ == "__main__":
    main()
