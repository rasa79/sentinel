"""Toy 'orders' service entrypoint (PLAN.md Task 1.1/1.2).

Runs the shared FastAPI app with the SERVICE_NAME defaulting to "orders". Invoked as
``python -m services.orders`` (see the demo_stack Dockerfile / compose).
"""

from __future__ import annotations

import os

from .common import create_app

app = create_app(os.environ.get("SERVICE_NAME", "orders"))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
