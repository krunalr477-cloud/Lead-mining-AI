# syntax=docker/dockerfile:1.7
# =============================================================================
# LeadMine AI — backend image (multi-stage, uv-managed).
#
# Stages:
#   base    — python:3.12-slim with the uv binary copied in (shared toolchain)
#   builder — resolves the *frozen* runtime venv (main deps only) into /app/.venv
#   api     — slim FastAPI/uvicorn runtime, no browser. Target: `api`.
#   worker  — builder venv + dev group (playwright) + chromium for crawler tier-2.
#             Target: `worker`.
#
# Both runtime stages run as a non-root `app` user and go through
# docker-entrypoint.sh, which runs `alembic upgrade head` only when
# RUN_MIGRATIONS=1 (set on the api service), then execs the CMD.
# =============================================================================

# --- Shared base: Python + uv -------------------------------------------------
FROM python:3.12-slim AS base
# uv's static binary — pinned by digest-tagged image, copied so no curl needed.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app


# --- Builder: frozen runtime venv (main deps only) ---------------------------
FROM base AS builder
# Layer-cache the dependency solve: only pyproject + lock invalidate it.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


# --- Builder (worker): venv WITH dev group (playwright package) ---------------
FROM base AS builder-worker
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project


# --- API runtime --------------------------------------------------------------
FROM python:3.12-slim AS api
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# libpq for psycopg (sync path / alembic) + curl-free healthcheck uses stdlib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app \
    # In-container REPO_ROOT resolves to "/", so the local-disk export driver and
    # the mock Sheets JSON/xlsx mirror write to /exports. Pre-create it writable.
    && mkdir -p /exports && chown app:app /exports

# Runtime venv from the builder, then the application source.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app . /app
RUN chmod +x /app/docker-entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --- Worker runtime (crawler tier-2 needs a real browser) --------------------
FROM python:3.12-slim AS worker
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /ms-playwright && chown app:app /ms-playwright \
    # Workers run export/sheet-sync tasks that write to /exports (REPO_ROOT="/").
    && mkdir -p /exports && chown app:app /exports

# venv includes the playwright *package*; the browser binary + its OS deps are
# installed next via `playwright install --with-deps chromium` (arm64-native).
COPY --from=builder-worker --chown=app:app /app/.venv /app/.venv
RUN --mount=type=cache,target=/var/cache/apt \
    playwright install --with-deps chromium \
    && chown -R app:app /ms-playwright

COPY --chown=app:app . /app
RUN chmod +x /app/docker-entrypoint.sh

USER app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
# Overridden by compose (the 12-queue celery worker command); a sane default.
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=INFO"]
