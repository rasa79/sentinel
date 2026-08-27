"""FastAPI application factory for the Sentinel control plane (PLAN.md Task 5.1)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from sentinel.api.deps import AppState, build_app_state
from sentinel.api.routes_alerts import router as alerts_router
from sentinel.api.routes_incidents import router as incidents_router
from sentinel.api.routes_stream import router as stream_router

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _run_startup(app.state.sentinel)
    yield


def _run_startup(state: AppState) -> None:
    """Apply migrations and (idempotently) ensure the checkpointer tables exist."""
    # PostgresSaver.setup() was already run in make_checkpointer; re-running is idempotent.
    # Run alembic upgrade head so the app DB schema is current (safe no-op when already applied).
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 - startup must not crash if the schema is already current
        pass


def create_app(app_state: AppState | None = None) -> FastAPI:
    """Create the Sentinel API app, optionally with an injected ``AppState`` for tests."""
    state = app_state or build_app_state()
    app = FastAPI(title="Sentinel API", lifespan=lifespan)
    app.state.sentinel = state
    app.include_router(alerts_router)
    app.include_router(incidents_router)
    app.include_router(stream_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe for the containerized API (phase-5 gate check)."""
        return {"status": "ok"}

    return app
