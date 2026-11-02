ARG CANN_BASE_IMAGE
FROM ${CANN_BASE_IMAGE} AS runtime-base
USER root
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PSYCOPG_IMPL=python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ffmpeg libgl1 libglib2.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY platform /app/platform
RUN python3 -m pip install 'numpy<2' 'setuptools<70' wheel cython \
    && python3 -m pip install 'torch==2.2.2' 'torchvision==0.17.2' \
    && python3 -c 'import torch; assert torch.version.cuda is None' \
    && python3 -m pip install '/app/platform[highgo]' \
    && python3 -m pip install --no-build-isolation \
       -c /app/platform/pipeline-constraints.txt -r /app/platform/pipeline-requirements.txt \
       'ultralytics==8.4.102' \
    && python3 -m pip freeze > /app/python-dependencies.txt \
    && dpkg-query -W > /app/os-dependencies.txt
COPY run_platform.py main_optimized.py /app/
COPY configs/app_config.yaml /app/configs/app_config.yaml
COPY configs/hydra /app/configs/hydra
COPY elements /app/elements
COPY nodes /app/nodes
COPY byte_tracker /app/byte_tracker
COPY utils_local /app/utils_local
COPY services/*.py /app/services/

FROM runtime-base AS model-converter
RUN python3 -m pip install 'onnx==1.16.2' 'protobuf==3.20.3'
COPY scripts/convert_ascend_models.py /app/scripts/convert_ascend_models.py
CMD ["python3", "/app/scripts/convert_ascend_models.py", "--help"]

FROM runtime-base AS production
# This directory must contain aarch64 libpq and its complete vendor dependency chain.
COPY deploy/intranet/highgo-driver/arm64/ /opt/highgo/lib/
RUN printf '%s\n' /opt/highgo/lib > /etc/ld.so.conf.d/00-highgo.conf \
    && ln -sf libpq.so.5 /opt/highgo/lib/libpq.so \
    && ldconfig
COPY deploy/intranet/runtime_check.py deploy/intranet/init_db.py deploy/intranet/topic_acl.py /app/deploy/
COPY deploy/intranet/seed_sources.py deploy/intranet/test-sources.json /app/deploy/
ENV LD_LIBRARY_PATH=/opt/highgo/lib:${LD_LIBRARY_PATH}
ENV LD_PRELOAD=/opt/highgo/lib/libpq.so.5
ENV PYTHONPATH=/app/platform:/app
RUN python3 /app/deploy/runtime_check.py --libraries-only
RUN mkdir -p /app/logs /app/weights /app/test_videos /survey /calibration /hls \
    /pipeline-output /pipeline-spool /trajectory-archive
EXPOSE 8000
CMD ["python3", "run_platform.py"]
