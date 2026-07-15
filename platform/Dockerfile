FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY pipeline-requirements.txt ./
COPY pipeline-constraints.txt ./

# Install Python dependencies
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir "numpy<2" "setuptools<70.0" wheel cython \
    && pip install --no-cache-dir torch==2.2.2 torchvision==0.17.2 \
    && pip install --no-cache-dir -c pipeline-constraints.txt -r pipeline-requirements.txt

# Create necessary directories
RUN mkdir -p /hls /calibration

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
