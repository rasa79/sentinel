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
