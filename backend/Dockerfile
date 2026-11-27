# Stages: builder -> base-runtime -> api | worker.
# `worker` is the LAST stage, so an untargeted `docker build` produces the full
# (OCR-capable) worker image. CI builds `--target api` and `--target worker`.
# Base images are pinned by digest; the tag is kept for readability. Refresh
# with `docker buildx imagetools inspect python:3.12-slim`.
FROM python:3.15-slim@sha256:63bb298d2b7b88f176f51b5189f54ce6535c997682ea70885d2132f5d473a8a5 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first (layer cache), installed from the hashed lockfile.
COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini /app/
COPY alembic /app/alembic
COPY app /app/app
RUN uv sync --frozen --no-dev --no-editable

# Shared runtime: no OCR packages, non-root user, read-only application files.
# The virtualenv lives outside /app so the dev compose bind mount
# (./backend:/app) does not hide it.
FROM python:3.15-slim@sha256:63bb298d2b7b88f176f51b5189f54ce6535c997682ea70885d2132f5d473a8a5 AS base-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 rudix \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/rudix \
        --create-home --shell /usr/sbin/nologin rudix

# Application files are owned by root and only readable by the runtime user;
# the app writes nothing under /app or /opt/venv at runtime (temp files and
# the beat schedule go to /tmp).
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY scripts /app/scripts

FROM base-runtime AS api

USER 10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Worker: adds Tesseract (eng, ara, fas) and Poppler for OCR. Keep this stage last.
FROM base-runtime AS worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-ara \
        tesseract-ocr-fas \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

USER 10001

# Pings this container's own Celery node. The beat service runs from this image
# too and has no worker node, so compose disables the healthcheck for beat.
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=5 \
    CMD celery -A app.workers.celery_app:celery_app inspect ping -d "celery@$HOSTNAME" --timeout 10 >/dev/null || exit 1

CMD ["celery", "-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO"]
