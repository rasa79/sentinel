"""E2E: bad_deploy chaos → full investigation through the live API (PLAN.md Task 7.3)."""

from __future__ import annotations

import uuid

import pytest
from helpers import (
    API,
    CHAOS_HOST,
    SERVICE,
    SERVICE_PORT,
    approve_incident,
    fire_alert,
    generate_traffic,
    inject_chaos,
    wait_for_active_chaos,
    wait_for_chaos_reset,
    wait_incident_status,
)

pytestmark = pytest.mark.e2e


def test_bad_deploy_e2e() -> None:
    inject_chaos(CHAOS_HOST, SERVICE_PORT, "bad_deploy", 90)
    wait_for_active_chaos(CHAOS_HOST, SERVICE_PORT, "bad_deploy")
    generate_traffic(CHAOS_HOST, SERVICE_PORT)
    incident_id = fire_alert(API, SERVICE, f"bad-deploy-rollback-{uuid.uuid4().hex[:8]}")
    inc = wait_incident_status(API, incident_id, {"awaiting_approval", "resolved", "escalated"})
    if inc["incident"]["status"] == "awaiting_approval":
        approve_incident(API, incident_id)
    inc = wait_incident_status(API, incident_id, {"resolved", "escalated"})
    assert inc["incident"]["status"] in {"resolved", "escalated"}
    assert inc["state"].get("hypothesis"), "expected a hypothesis"
    assert inc["state"].get("remediation"), "expected a remediation"
    wait_for_chaos_reset(CHAOS_HOST, SERVICE_PORT, timeout=150)
