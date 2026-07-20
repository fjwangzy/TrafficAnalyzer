FROM python:3.12-slim

# Platform and detector runtime dependencies. The canonical image remains
# CPU-compatible; GPU runtime exposure is an external deployment concern.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency metadata first so source-only changes keep the dependency
# layers cached.
COPY platform/pyproject.toml platform/alembic.ini \
    platform/pipeline-requirements.txt platform/pipeline-constraints.txt \
    /app/platform/
COPY platform/app /app/platform/app
COPY platform/alembic /app/platform/alembic

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e /app/platform \
    && pip install --no-cache-dir "numpy<2" "setuptools<70.0" wheel cython \
    && pip install --no-cache-dir torch==2.2.2 torchvision==0.17.2 \
    && pip install --no-cache-dir --no-build-isolation \
        -c /app/platform/pipeline-constraints.txt \
        -r /app/platform/pipeline-requirements.txt

# Bake the detector implementation into the Platform image. Large runtime
# assets (weights and videos) are mounted read-only by Compose.
COPY run_platform.py main_optimized.py /app/
COPY configs /app/configs
COPY elements /app/elements
COPY nodes /app/nodes
COPY byte_tracker /app/byte_tracker
COPY utils_local /app/utils_local
COPY services/*.py /app/services/

RUN mkdir -p \
    /app/logs \
    /app/weights \
    /app/test_videos \
    /hls \
    /calibration \
    /pipeline-output \
    /pipeline-spool \
    /survey

EXPOSE 8000

CMD ["python", "run_platform.py"]
