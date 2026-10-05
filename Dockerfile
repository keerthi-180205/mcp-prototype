# Multi-stage / lightweight Python base image
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if needed and update pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for caching efficiency
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source, scripts, tests, and documentation
COPY server/ ./server/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY README.md .
COPY architecture.md .
COPY .env.example .

# Create and switch to non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# MCP server operates over standard I/O (stdio) transport
CMD ["python", "-m", "server.server"]
