-- Pharma analytics mart (SQLite). Mirror of packages/db/migrations/002_pharma_datamart.sql
-- Canonical copy in mono: packages/db/migrations/002_pharma_datamart.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
  catalog_id  TEXT NOT NULL PRIMARY KEY,
  articolo    TEXT NOT NULL,
  prezzo      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_articolo ON products (articolo);

CREATE TABLE IF NOT EXISTS sales (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  product_catalog_id  TEXT NOT NULL REFERENCES products(catalog_id),
  year                INTEGER NOT NULL,
  month               INTEGER NOT NULL,
  prov                TEXT,
  pieces              INTEGER NOT NULL,
  value               REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_year ON sales (year);
CREATE INDEX IF NOT EXISTS idx_sales_year_month ON sales (year, month);
CREATE INDEX IF NOT EXISTS idx_sales_fk_prod ON sales (product_catalog_id);

CREATE TABLE IF NOT EXISTS target (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  product_catalog_id  TEXT NOT NULL REFERENCES products(catalog_id),
  year                INTEGER NOT NULL,
  month               INTEGER NOT NULL,
  prov                TEXT NOT NULL,
  pieces              INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_target_lookup ON target (prov, year, month);
CREATE INDEX IF NOT EXISTS idx_target_fk_prod ON target (product_catalog_id);
