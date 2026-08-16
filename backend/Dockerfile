# syntax=docker/dockerfile:1
# check=error=true

# Single source of truth for the Python base image across both stages below.
# Pin the newest supported major, never `latest`. The major must match
# /.python-version — CI fails the build if they drift
# (reusable-application-checks.yml), and that check also covers the ensurepip
# path near the bottom of this file, which hardcodes the same minor. The digest
# has to be a literal here and cannot move into .python-version: it is a content
# hash, not something derivable from a version string.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

FROM ${PYTHON_IMAGE} AS wheels

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1

WORKDIR /build
COPY requirements.txt ./
RUN python -m pip wheel --require-hashes --wheel-dir=/wheels -r requirements.txt

FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="VideoLens backend" \
      org.opencontainers.image.description="VideoLens API and asynchronous media-analysis worker" \
      org.opencontainers.image.source="https://github.com/thisisgaganbirru/videolens" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_COMPILE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEMP_DIR=/tmp/videolens

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && groupadd --gid 10001 videolens \
    && useradd --uid 10001 --gid 10001 --no-log-init --create-home videolens

WORKDIR /app
COPY --from=wheels /wheels /wheels
COPY requirements.txt ./
RUN python -m pip install --no-index --require-hashes --find-links=/wheels -r requirements.txt \
    && python -m pip uninstall --yes pip setuptools wheel \
    && rm -rf /wheels /usr/local/lib/python3.13/ensurepip

COPY --chown=10001:10001 app ./app
RUN mkdir -p /tmp/videolens \
    && chown -R 10001:10001 /app /tmp/videolens

USER 10001:10001

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
