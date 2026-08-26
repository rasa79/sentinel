"""Toy 'inventory' service entrypoint (PLAN.md Task 1.2)."""

from __future__ import annotations

import os

from .common import create_app

app = create_app(os.environ.get("SERVICE_NAME", "inventory"))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
