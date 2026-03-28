# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY app/frontend/package.json ./
RUN npm install
COPY app/frontend/ .
RUN npm run build

# ── Stage 2: Python backend + compiled frontend ────────────────────────────────
FROM python:3.12-slim

# System deps for pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY app/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# App code
COPY app/backend/app.py app/backend/db_store.py app/backend/001_dashboard_app.sql ./

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Data volume mount point
RUN mkdir -p /data /tmp/flask_sessions

# Non-root user
RUN useradd -m -u 1001 pharma && chown -R pharma:pharma /app /data /tmp/flask_sessions
USER pharma

EXPOSE 8080

CMD gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 app:application
