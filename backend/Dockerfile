# syntax=docker/dockerfile:1
# Backend — AI Agent Failure Memory (FastAPI)
#
# Multi-stage build: dependency stage -> minimal non-root runtime image.
# Runs on Linux containers (linux/amd64 + linux/arm64) for Windows/macOS/Linux
# hosts through Docker Desktop or Docker Engine. No host Python required.
#
# The host tree is NOT bind-mounted (see compose.yaml); only files copied into
# the image below are shipped.

# --------------------------------------------------------------------------- #
# Base stage — shared by deps and production so paths/versions always match
# --------------------------------------------------------------------------- #
FROM python:3.11.17-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --------------------------------------------------------------------------- #
# Dependencies stage
# --------------------------------------------------------------------------- #
FROM base AS deps

# gcc is only a safety net for any dependency without a prebuilt wheel for the
# target platform; it is deliberately NOT copied into the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install the project's existing dependency manifest (pinned at the manifest
# level: requirements.txt). npm-style lockfiles are not used by this project.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --------------------------------------------------------------------------- #
# Production stage
# --------------------------------------------------------------------------- #
FROM base AS production

# libsqlite3-0: explicit runtime dependency for stdlib sqlite3 (memory store).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser

# Python packages installed by the deps stage.
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Application code (tests are excluded via .dockerignore).
COPY backend/ ./backend/
COPY run.py ./

# Build-time smoke check: the real application module must import with the
# installed dependency set. MEMORY_DATABASE=":memory:" keeps this check from
# creating a database file as root.
RUN MEMORY_DATABASE=":memory:" python -c "from backend.api.routes import app; assert app.title"

# Dedicated persistent directory for SQLite + evaluation reports. compose.yaml
# mounts a named volume here; ownership is copied to the volume on first use.
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

# Container defaults (override per-service in compose.yaml).
ENV MEMORY_DATABASE=/app/data/memory.db \
    EVALUATION_REPORT_PATH=/app/data/evaluation_report.json \
    APP_ENV=production

EXPOSE 8000

# Container health check against the existing /api/health endpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

# Bind 0.0.0.0 inside the container so the published host port works.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
