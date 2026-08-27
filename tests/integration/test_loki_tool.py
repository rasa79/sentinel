"""Integration test for the Loki client against the live demo stack (Task 4.1).

Requires the stack (``docker compose up -d --build``). Marked ``integration``.
"""

from __future__ import annotations

import time
from datetime import timedelta

import httpx
import pytest

from sentinel.config import Settings
from sentinel.tools.loki import query_logs

pytestmark = pytest.mark.integration


def test_loki_tool_returns_injected_error_lines() -> None:
    settings = Settings()
    service = "orders"
    # Inject an error_burst so the service emits ERROR-structure log lines to Loki.
    httpx.post("http://localhost:9001/chaos", json={"type": "error_burst", "duration_seconds": 30})
    for _ in range(4):
        httpx.get("http://localhost:9001/work")
    time.sleep(3)  # allow the Loki push thread + ingest to land

    logs = query_logs(service, since=timedelta(minutes=5), limit=10, base_url=settings.loki.url)
    assert len(logs) >= 1
    assert any(log.message == "work" for log in logs)
