# Dashboard subproject plan (`as-pizeta-dashboard` → `mono/apps/dashboard`)

Working notes for bringing the legacy dashboard into the mono tree. **Source reviewed:** sibling folder `as/pizeta/dashboard` (existing Git repo `as-pizeta-dashboard`).

## 1. Legacy inventory (what exists today)

| Area | Location (legacy) | Notes |
|------|-------------------|--------|
| App shell | `app/` | Flask backend + Vite/React frontend; `Dockerfile` at repo root, Podman-oriented build |
| Backend | `app/backend/app.py` | Google OAuth (Authlib), TOTP 2FA, sessions, PDF upload path via `pdfplumber`, static SPA from `app/frontend/dist` |
| Frontend | `app/frontend/` | Vite, pages: Login, 2FA, Dashboard |
| Data / ETL | SQLite in `DATA_DIR` | **`pizeta.sqlite`** — tables `dashboard_user`, `dashboard_upload` (DDL in mono `packages/db/migrations/001_dashboard_app.sql`). Legacy ETL tree (`data/schema.sql`, parsers) not in this repo yet; target `services/ingest/` + shared schema. |
| Docs | Root `README.md` (incl. Podman), `DEPLOY_GUIDE.md` (Cloud Run) | Two deployment stories |

**Gap vs platform target:** the app now uses **SQLite** for users and PDF upload rows; the richer **star schema** (`import_batch`, `fact_measure`, …) and ingest pipeline are still future work in `packages/db` + `services/ingest`. Upload rows are still stored as **JSON blobs** per upload until normalized tables exist.

## 2. Decisions to confirm (before large moves)

1. **Submodule vs copy:** Prefer **`git submodule add`** into `apps/dashboard` so `as-pizeta-dashboard` stays the canonical app remote (matches [REPOS.md](../../../docs/REPOS.md)). Use copy-only slices only if you are abandoning the separate repo.
2. **Local dev auth:** Align with [OVERVIEW.md](../../../docs/OVERVIEW.md): `AUTH_MODE=development` (or equivalent) to skip OAuth/TOTP on localhost; production keeps current behavior.
3. **Schema ownership:** Plan to move **`schema.sql`** (and migration story) to **`packages/db/`** when the team is ready; until then submodule can keep it in `data/` and mono docs stay honest in CONTINUATION.
4. **Ingest / parsers:** Target home is **`services/ingest/`**; first milestone can leave ETL in the dashboard repo and only **document** boundaries, or extract one script at a time.

## 3. Suggested phases

### Phase A — Wire the tree (low risk)

- Add submodule: `git submodule add <as-pizeta-dashboard-url> apps/dashboard` from mono root (or rename legacy remote and push if the GitHub repo URL differs).
- Remove duplicate **placeholder** `apps/dashboard/README.md` in mono **only if** the submodule brings its own README at the same path (per REPOS).
- Update [CONTINUATION.md](../../../docs/CONTINUATION.md): dashboard path is populated; note any remaining work-only-in-legacy.

### Phase B — Developer experience

- Single **root-level or app-level** doc for “how to run dashboard from mono” (env vars, `SECRET_KEY`, Google keys, `/data` volume). **Partial:** [GETTING_STARTED.md](../../../docs/GETTING_STARTED.md) points at `apps/dashboard/` + `app/backend` / `app/frontend`; app `README.md` covers local dev and Podman.
- Consolidate or cross-link the two deployment guides so mono does not carry conflicting “source of truth” without a label (e.g. `DEPLOY_PODMAN.md` vs `DEPLOY_CLOUD_RUN.md`). **Partial:** `DEPLOY_GUIDE.md` is explicitly **Cloud Run only** with a pointer to README for Podman; optional future split into `DEPLOY_CLOUD_RUN.md` / `DEPLOY_PODMAN.md` if docs grow.

### Phase C — Platform alignment

- Implement **development auth bypass** safely (never enabled in production builds).
- Point API and ETL at **one database owner** (SQLite file served by one process), matching OVERVIEW. **Partial:** dashboard API owns **`pizeta.sqlite`** (users + uploads); DDL baseline in **`packages/db/migrations/001_dashboard_app.sql`**.
- Migrate **full analytics schema + migration tooling** to `packages/db/`; point `etl_build_db.py` (or successor) at that path.
- Move **parse/sync** entrypoints toward `services/ingest/` with clear inputs/outputs (files → DB).

### Phase D — Hardening

- Tests for parsers / ETL where feasible; CI in dashboard repo or mono (policy TBD).
- Secrets: `.env.example` only in repo; document required variables in GETTING_STARTED or app README.

## 4. Open questions

- Does production today use **Cloud Run** only, **VM + Podman**, or both? Plan doc structure should reflect the active path.
- Production cutover: ensure **`pizeta.sqlite`** is on the persisted volume (replacing any remaining JSON-only deploys).
- Further flattening (e.g. single `src/`) is optional; `app/backend/` and `app/frontend/` are the current layout.

## 5. References

- Legacy root README: pharma analytics, OAuth, TOTP, PDF scraping.
- Mono rules: `.cursor/rules/pizeta-workspace.mdc` (copy discipline, one subproject at a time).
