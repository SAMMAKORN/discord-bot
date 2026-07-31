FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Create non-root user for security
RUN addgroup --system bot && adduser --system --ingroup bot botuser

# Database volume
RUN mkdir -p /data && chown botuser:bot /data

USER botuser

# Database path points to volume
ENV DB_PATH=/data/users.db

CMD ["python", "main.py"]
