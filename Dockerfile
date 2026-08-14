# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.lock

# Copy application (main.py + bot/ package)
COPY main.py .
COPY bot/ ./bot/

# Default database path for Docker
ENV DB_PATH=/app/data/bot.db
ENV ENCRYPTION_KEY_FILE=/app/data/.encryption_key

# A running container implies the foreground bot process is alive. Verify that
# its SQLite database exists and is readable without relying on procps/pgrep.
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c 'import os, sqlite3; p=os.environ["DB_PATH"]; assert os.path.isfile(p); sqlite3.connect(p).execute("SELECT 1")' || exit 1

# Entrypoint fixes volume mount permissions before running as botuser
RUN printf '#!/bin/sh\nset -e\nDATA_DIR="$(dirname "${DB_PATH}")"\nmkdir -p "$DATA_DIR"\nchown -R botuser:bot "$DATA_DIR" 2>/dev/null || true\nchmod 755 "$DATA_DIR" 2>/dev/null || true\nexec su botuser -s /bin/sh -c "cd /app && python main.py"\n' > /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

# Create non-root user
RUN addgroup --system bot && adduser --system --ingroup bot botuser \
    && mkdir -p /app/data && chown -R botuser:bot /app/data

# Run entrypoint as root (to fix volume permissions) then drop to botuser
USER root
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD []
