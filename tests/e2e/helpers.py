"""E2E helpers for the Sentinel demo stack.

These let tests and the demo script poll the chaos state instead of blindly sleeping, and inject
chaos deterministically. Used by the Phase 7 E2E scenarios and the `sentinel demo` walkthrough.
"""

from __future__ import annotations

import time
from typing import Any

import httpx


def chaos_status(base_url: str, port: int, timeout: float = 5.0) -> dict[str, Any]:
    """GET /chaos/status for a toy service. Returns e.g. ``{"active": "error_burst", ...}``."""
    resp = httpx.get(f"{base_url}:{port}/chaos/status", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def inject_chaos(
    base_url: str, port: int, chaos_type: str, duration_seconds: float = 60.0
) -> dict[str, Any]:
    """POST /chaos to activate a fault for a given duration."""
    resp = httpx.post(
        f"{base_url}:{port}/chaos",
        json={"type": chaos_type, "duration_seconds": duration_seconds},
        timeout=5.0,
    )
    resp.raise_for_status()
    return resp.json()


def wait_for_active_chaos(
    base_url: str,
    port: int,
    expected_type: str,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> dict[str, Any]:
    """Poll /chaos/status until the given fault is active, returning the final status dict."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = chaos_status(base_url, port)
        if status.get("active") == expected_type:
            return status
        time.sleep(interval)
    raise TimeoutError(f"{expected_type!r} never became active within {timeout}s")


def wait_for_chaos_reset(
    base_url: str,
    port: int,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> dict[str, Any]:
    """Poll /chaos/status until the fault has reset (``active`` is ``None``)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = chaos_status(base_url, port)
        if status.get("active") is None:
            return status
        time.sleep(interval)
    raise TimeoutError(f"chaos did not reset within {timeout}s (last status: {status})")


# --------------------------------------------------------------------------- incident/API helpers


def fire_alert(
    api_base: str,
    service: str,
    alertname: str,
    severity: str = "critical",
    timeout: float = 5.0,
) -> str:
    """POST an Alertmanager-style alert and return the created/deduped incident id."""
    resp = httpx.post(
        f"{api_base}/alerts/webhook",
        json={
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": alertname,
                        "service": service,
                        "severity": severity,
                    },
                    "annotations": {"summary": f"{service} {alertname} detected"},
                }
            ]
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["incident_id"]


def get_incident(api_base: str, incident_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """GET /incidents/{id}; return the JSON body."""
    resp = httpx.get(f"{api_base}/incidents/{incident_id}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def wait_incident_status(
    api_base: str,
    incident_id: str,
    targets: set[str],
    timeout: float = 200.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll /incidents/{id} until the incident reaches one of ``targets``; return the body."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = get_incident(api_base, incident_id)
        if body["incident"]["status"] in targets:
            return body
        time.sleep(interval)
    raise TimeoutError(f"incident {incident_id} never reached {sorted(targets)!r}")


def approve_incident(api_base: str, incident_id: str, timeout: float = 5.0) -> None:
    """POST /incidents/{id}/approve to resume the interrupted investigation."""
    resp = httpx.post(f"{api_base}/incidents/{incident_id}/approve", timeout=timeout)
    resp.raise_for_status()


# ------------------------------------------------------------ shared E2E scenario defaults
API = "http://localhost:8000"
CHAOS_HOST = "http://localhost"
SERVICE = "orders"
SERVICE_PORT = 9001


def generate_traffic(base_url: str, port: int, hits: int = 4) -> None:
    """Hit /work a few times so an active chaos fault manifests in the metrics/logs pipeline."""
    for _ in range(hits):
        try:
            httpx.get(f"{base_url}:{port}/work", timeout=8)
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
