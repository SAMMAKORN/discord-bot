FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Create non-root user for security
RUN addgroup --system bot && adduser --system --ingroup bot botuser

# Database volume (mounted at /app/data)
RUN mkdir -p /app/data && chown botuser:bot /app/data

USER botuser

# Default database path for Docker
ENV DB_PATH=/app/data/bot.db

CMD ["python", "main.py"]
