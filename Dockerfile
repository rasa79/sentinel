# Sentinel API container image (PLAN.md Task 5.1).
# Uses the uv-managed environment + the pinned uv.lock; installs prod deps only.
FROM python:3.12-slim

# uv is the package + environment manager (LEARN[01]).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the project manifest first so dependency layers cache across rebuilds.
COPY pyproject.toml uv.lock alembic.ini config.yaml ./
COPY src ./src
COPY scripts ./scripts
COPY alembic ./alembic
COPY runbooks ./runbooks
COPY README.md KNOWN_LIMITATIONS.md LEARN_INDEX.md ./

# Install the project + prod dependencies (skip dev group).
RUN uv sync --no-dev --frozen

# Runnable entry point via uvicorn (factory pattern).
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "sentinel.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
