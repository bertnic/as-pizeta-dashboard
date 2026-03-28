-- Pharma datamart (SQLite). Apply via etl_build_db.py
-- Canonical copy in mono: packages/db/migrations/002_pharma_datamart.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batch (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_path   TEXT NOT NULL,
  file_name     TEXT NOT NULL,
  source_kind   TEXT NOT NULL, -- xlsx | pdf
  loaded_at     TEXT NOT NULL DEFAULT (datetime('now')),
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS fact_measure (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id         INTEGER NOT NULL REFERENCES import_batch(id) ON DELETE CASCADE,
  sheet            TEXT NOT NULL,
  geo_code         TEXT,
  geo_label        TEXT,
  agent_name       TEXT,
  hierarchy_level  TEXT,
  product_name     TEXT,
  year             INTEGER,
  month            INTEGER,
  day              INTEGER,
  metric           TEXT NOT NULL,
  value            REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_batch_sheet
  ON fact_measure (batch_id, sheet);

CREATE INDEX IF NOT EXISTS idx_fact_geo_product_period
  ON fact_measure (batch_id, sheet, geo_code, product_name, year, month, metric);

-- Target pezzi (premio / piano) — da SEDRAN DEF e/o foglio manuale 1TQAG…
CREATE TABLE IF NOT EXISTS TARGET (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id   INTEGER NOT NULL REFERENCES import_batch(id) ON DELETE CASCADE,
  cod        TEXT,
  articolo   TEXT NOT NULL,
  anno       INTEGER NOT NULL,
  mese       INTEGER NOT NULL,
  prov       TEXT NOT NULL,
  qta        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_target_batch ON TARGET (batch_id);
CREATE INDEX IF NOT EXISTS idx_target_lookup ON TARGET (batch_id, prov, articolo, anno, mese);

-- Listino / prezzi di riferimento
CREATE TABLE IF NOT EXISTS PRODOTTI (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id   INTEGER NOT NULL REFERENCES import_batch(id) ON DELETE CASCADE,
  cod        TEXT,
  articolo   TEXT NOT NULL,
  prezzo     REAL NOT NULL,
  UNIQUE (batch_id, articolo)
);

CREATE INDEX IF NOT EXISTS idx_prodotti_batch ON PRODOTTI (batch_id);

-- Fatturato (vendite) — da foglio manuale FATTURATO o foglio legacy 1W7R3…
CREATE TABLE IF NOT EXISTS FATTURATO (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id   INTEGER NOT NULL REFERENCES import_batch(id) ON DELETE CASCADE,
  cod        TEXT,
  articolo   TEXT NOT NULL,
  anno       INTEGER NOT NULL,
  mese       INTEGER NOT NULL,
  prov       TEXT,
  qta        REAL NOT NULL,
  valore     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fatturato_batch ON FATTURATO (batch_id);
