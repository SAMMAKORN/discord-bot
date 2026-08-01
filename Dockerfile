FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Database path is fixed to /app/data/bot.db — do NOT make it configurable via ENV
# Changing the path causes data loss on deploy (file written outside named volume)

# Healthcheck: verify bot process is running and DB is initialized
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -x python > /dev/null && test -f /app/data/bot.db || exit 1

# Entrypoint fixes volume mount permissions before running as botuser
# แก้ chown botuser:bot เป็น chown -R botuser:bot
RUN printf '#!/bin/sh\nset -e\nmkdir -p /app/data\nchown -R botuser:bot /app/data 2>/dev/null || true\nchmod 755 /app/data 2>/dev/null || true\nexec su botuser -s /bin/sh -c "cd /app && python main.py"\n' > /docker-entrypoint.sh \
    && chmod +x /docker-entrypoint.sh

# Create non-root user
RUN addgroup --system bot && adduser --system --ingroup bot botuser \
    && mkdir -p /app/data && chown -R botuser:bot /app/data

# Run entrypoint as root (to fix volume permissions) then drop to botuser
USER root
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD []