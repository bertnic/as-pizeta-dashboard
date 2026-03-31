-- Platform tables: users (multi-app auth), Strame (hcp, structures, visits, visit_plan), Notaspese (receipts).
-- Apply after 001_dashboard_app.sql (+ optional 002 mart). Keep in sync with mono packages/db/migrations/003_platform_new_tables.sql
-- Target database file: pizeta.sqlite

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- users — authentication / profile (Dashboard, Strame, Notaspese)
-- Legacy dashboard_user: copy via mono packages/db/scripts/migrate.py; optional DROP after verification.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  email              TEXT NOT NULL UNIQUE,
  totp_secret        TEXT,
  display_name       TEXT,
  picture_url        TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- ---------------------------------------------------------------------------
-- structures — sites / organizations (Strame)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS structures (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  name               TEXT NOT NULL,
  address            TEXT,
  provincia          TEXT,
  phone              TEXT,
  email              TEXT,
  hours_text         TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_structures_provincia ON structures (provincia);
CREATE INDEX IF NOT EXISTS idx_structures_name ON structures (name);

-- ---------------------------------------------------------------------------
-- hcp — healthcare professionals (Strame)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hcp (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  first_name              TEXT,
  last_name               TEXT,
  structure_label         TEXT,
  activity_site           TEXT,
  specialty               TEXT,
  email                   TEXT,
  phone                   TEXT,
  provincia               TEXT,
  out_of_territory        INTEGER NOT NULL DEFAULT 0,
  segment_value           TEXT,
  potenziale_generale     TEXT,
  potenziale_azienda      TEXT,
  profilo                 TEXT,
  stile_comportamentale   TEXT,
  sponsor                 TEXT,
  frequenza               TEXT,
  in_piano                INTEGER NOT NULL DEFAULT 0,
  ultima_visita           TEXT,
  structure_id            INTEGER REFERENCES structures (id),
  created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_hcp_provincia ON hcp (provincia);
CREATE INDEX IF NOT EXISTS idx_hcp_structure_id ON hcp (structure_id);
CREATE INDEX IF NOT EXISTS idx_hcp_names ON hcp (last_name, first_name);

-- ---------------------------------------------------------------------------
-- visits — completed visits (Strame)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS visits (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  hcp_id             INTEGER NOT NULL REFERENCES hcp (id),
  structure_id       INTEGER REFERENCES structures (id),
  rep_user_id        INTEGER REFERENCES users (id),
  visited_at         TEXT NOT NULL,
  outcome            TEXT,
  notes              TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_visits_hcp ON visits (hcp_id);
CREATE INDEX IF NOT EXISTS idx_visits_visited_at ON visits (visited_at);
CREATE INDEX IF NOT EXISTS idx_visits_rep ON visits (rep_user_id);

-- ---------------------------------------------------------------------------
-- visit_plan — planned visits for a period (Strame); product term "plan"
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS visit_plan (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  period_start       TEXT NOT NULL,
  hcp_id             INTEGER NOT NULL REFERENCES hcp (id),
  structure_id       INTEGER REFERENCES structures (id),
  rep_user_id        INTEGER NOT NULL REFERENCES users (id),
  status             TEXT,
  notes              TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_visit_plan_period ON visit_plan (period_start);
CREATE INDEX IF NOT EXISTS idx_visit_plan_rep ON visit_plan (rep_user_id);

-- ---------------------------------------------------------------------------
-- receipts — expense / receipt lines (Notaspese); extend when app is defined
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS receipts (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id            INTEGER NOT NULL REFERENCES users (id),
  amount             REAL,
  currency           TEXT NOT NULL DEFAULT 'EUR',
  vendor             TEXT,
  category           TEXT,
  document_date      TEXT,
  image_storage_key  TEXT,
  raw_json           TEXT,
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_user ON receipts (user_id);
CREATE INDEX IF NOT EXISTS idx_receipts_document_date ON receipts (document_date);
