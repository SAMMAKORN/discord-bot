FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Default database path for Docker
ENV DB_PATH=/app/data/bot.db

# Entrypoint fixes volume mount permissions before running as botuser
RUN printf '#!/bin/sh\nset -e\nDATA_DIR="$(dirname "${DB_PATH}")"\nmkdir -p "$DATA_DIR"\nchown botuser:bot "$DATA_DIR" 2>/dev/null || true\nchmod 755 "$DATA_DIR" 2>/dev/null || true\nexec su botuser -s /bin/sh -c "cd /app && python main.py"\n' > /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

# Create non-root user
RUN addgroup --system bot && adduser --system --ingroup bot botuser \
    && mkdir -p /app/data && chown botuser:bot /app/data

# Run entrypoint as root (to fix volume permissions) then drop to botuser
USER root
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD []
