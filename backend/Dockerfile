# syntax=docker/dockerfile:1
# check=error=true

FROM python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1 AS wheels

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1

WORKDIR /build
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip wheel --require-hashes --wheel-dir=/wheels -r requirements.txt

FROM python:3.11-slim@sha256:a630a63cdb314e2d138a2fca3e375e319e8568346ffafac5b980f888630ac4f1 AS runtime

LABEL org.opencontainers.image.title="VideoLens backend" \
      org.opencontainers.image.description="VideoLens API and asynchronous media-analysis worker" \
      org.opencontainers.image.source="https://github.com/thisisgaganbirru/videolens" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEMP_DIR=/tmp/videolens

RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && groupadd --gid 10001 videolens \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home videolens

WORKDIR /app
COPY --from=wheels /wheels /wheels
COPY requirements.txt ./
RUN python -m pip install --no-index --require-hashes --find-links=/wheels -r requirements.txt \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /wheels /usr/local/lib/python3.11/ensurepip

COPY --chown=10001:10001 app ./app
RUN mkdir -p /tmp/videolens \
    && chown -R 10001:10001 /app /tmp/videolens

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
