FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared library
COPY shared /app/shared
RUN pip install --no-cache-dir /app/shared

# Copy and install vision service
COPY services/vision /app
RUN pip install --no-cache-dir .

EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
