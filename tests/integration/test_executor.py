"""Integration test for the Docker executor against the live compose stack (Task 4.3).

Restarts the real ``orders`` container. Requires the stack. Marked ``integration``.
"""

from __future__ import annotations

import time

import httpx
import pytest

from sentinel.config import Settings
from sentinel.tools.executor import RemediationNotAllowed, execute

pytestmark = pytest.mark.integration


def test_restart_orders_container_for_real() -> None:
    result = execute("restart_service", "orders", dry_run=False, settings=Settings())
    assert result.target_service == "orders"
    assert result.status == "ok"

    # Wait for the restarted container to come back healthy so later tests are stable.
    healthy = False
    for _ in range(20):
        try:
            if httpx.get("http://localhost:9001/healthz", timeout=2).status_code == 200:
                healthy = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    assert healthy, "orders did not return to healthy after restart"


def test_non_whitelisted_action_is_refused() -> None:
    with pytest.raises(RemediationNotAllowed):
        execute("drop_everything", "orders", dry_run=False, settings=Settings())
