-- Dashboard app runtime SQLite (PoC).
-- Keep in sync with mono: packages/db/migrations/001_dashboard_app.sql (canonical).

CREATE TABLE IF NOT EXISTS dashboard_user (
  email TEXT PRIMARY KEY NOT NULL,
  totp_secret TEXT NOT NULL,
  display_name TEXT,
  picture_url TEXT
);

CREATE TABLE IF NOT EXISTS dashboard_upload (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  label TEXT NOT NULL,
  rows_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dashboard_upload_created ON dashboard_upload (created_at);
