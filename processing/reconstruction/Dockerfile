# Build from processing/reconstruction only. No model assets enter the context.
FROM --platform=linux/amd64 pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_RETRIES=0 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    HOME=/tmp XDG_CACHE_HOME=/tmp/cache MPLCONFIGDIR=/tmp/matplotlib \
    YOLO_CONFIG_DIR=/tmp/ultralytics YOLO_AUTOINSTALL=false
RUN apt-get -o Acquire::Retries=0 update && \
    apt-get -o Acquire::Retries=0 install -y --no-install-recommends \
      git build-essential ffmpeg libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /opt/GVHMR
RUN git init . && git remote add origin https://github.com/zju3dv/GVHMR.git && \
    git fetch --depth=1 origin ee960bb6e2ea2d381aa97f08e9b71ef320b624b1 && \
    git checkout --detach FETCH_HEAD && \
    test "$(git rev-parse HEAD)" = ee960bb6e2ea2d381aa97f08e9b71ef320b624b1 && \
    git rev-parse HEAD > INSPECTED_REVISION && rm -rf .git
COPY requirements.runtime.txt /tmp/requirements.runtime.txt
RUN python -m pip install --no-cache-dir -r requirements.txt -r /tmp/requirements.runtime.txt && \
    python -m pip install --no-cache-dir --no-deps -e . && \
    python -m pip check && python -m pip freeze > /opt/runtime-freeze.txt
RUN mkdir -p /opt/GVHMR/inputs/checkpoints
ENTRYPOINT ["python", "-m", "processing.reconstruction.runtime"]
