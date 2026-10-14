# Multi-stage: build the virtualenv with uv, ship only the runtime.
ARG PYTHON_IMAGE=python:3.13-slim

FROM ${PYTHON_IMAGE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the project itself. psycopg[binary] bundles libpq, so no apt packages are needed.
COPY app ./app
COPY alembic.ini docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE} AS runtime

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER appuser
EXPOSE 8000

# urlopen raises on a non-2xx status, which fails the check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/api/health')"

# Applies migrations (unless RUN_MIGRATIONS=false), then execs the CMD.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
