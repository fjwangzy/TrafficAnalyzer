FROM --platform=linux/amd64 python:3.11

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy and install shared library
COPY shared /app/shared
RUN pip install --no-cache-dir /app/shared

# Copy and install operations service
COPY services/operations /app
RUN pip install --no-cache-dir .

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
