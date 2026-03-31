# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY app/frontend/package.json ./
RUN npm install
COPY app/frontend/ .
RUN npm run build

# ── Stage 2: Python backend + compiled frontend ────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Python deps
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# App code
COPY app/backend/app.py app/backend/db_store.py app/backend/datamart_summary.py app/backend/001_dashboard_app.sql app/backend/002_pharma_datamart.sql app/backend/003_platform_new_tables.sql app/backend/004_drop_dashboard_upload.sql ./

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Data volume mount point (mono layout not present in image → db_store uses /data)
ENV DATA_DIR=/data
RUN mkdir -p /data /tmp/flask_sessions

# Non-root user
RUN useradd -m -u 1001 pharma && chown -R pharma:pharma /app /data /tmp/flask_sessions
USER pharma

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 app:application
