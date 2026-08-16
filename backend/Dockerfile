# AI Daily News backend image
# Python 3.11-slim base; intentionally single-stage for v1 simplicity.
#
# Build:
#   docker build -t aidaily-backend ./backend
# Or via docker compose from repo root:
#   docker compose up -d --build

FROM python:3.11-slim AS runtime

# System deps:
# - gcc + libc-dev: needed to compile C extensions for selectolax / trafilatura
# - curl: lightweight health check helper (optional)
# Clean apt cache after install to keep the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        libxml2-dev \
        libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# Prevent Python from writing .pyc files and from buffering stdout/stderr.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy dependency manifest first to leverage Docker layer caching.
COPY pyproject.toml ./
COPY alembic.ini ./

# Install the package + runtime deps. `-e .` keeps the source tree editable
# inside the container (volume-mounted devs can iterate without rebuilding).
COPY app ./app
COPY migrations ./migrations
RUN pip install --no-cache-dir .

# Frontend is mounted read-only at runtime via docker-compose volume.
# We still create the directory so the container can boot standalone.
RUN mkdir -p /app/frontend /app/data /app/logs

# Default runtime config; overridable via `environment:` in docker-compose.yml
# or `docker run -e ...`.
ENV AIDAILY_HOST=0.0.0.0 \
    AIDAILY_PORT=8000 \
    AIDAILY_DB_PATH=/app/data/aidaily.db \
    AIDAILY_TZ=Asia/Shanghai

EXPOSE 8000

# Run alembic upgrade + start uvicorn.
# `alembic upgrade head` is idempotent — safe to run on every container start.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
