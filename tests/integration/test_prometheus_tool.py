"""Integration test for the Prometheus client against the live demo stack (Task 4.2).

Requires the stack. Each chaos type should produce a breach on its corresponding expression.
Marked ``integration``.
"""

from __future__ import annotations

import time
from datetime import timedelta

import httpx
import pytest

from sentinel.config import Settings
from sentinel.tools.prometheus import query_anomalies

pytestmark = pytest.mark.integration


def _inject_and_hit(chaos_type: str, hits: int) -> None:
    httpx.post(
        "http://localhost:9001/chaos",
        json={"type": chaos_type, "duration_seconds": 60},
    )
    for _ in range(hits):
        httpx.get("http://localhost:9001/work")


def test_each_chaos_type_produces_a_breach() -> None:
    base_url = Settings().prometheus.url
    window = timedelta(minutes=5)

    # error_burst -> error-rate breach
    _inject_and_hit("error_burst", 4)
    time.sleep(8)
    findings = query_anomalies("orders", window, base_url=base_url)
    err = [f for f in findings if f.metric == "http_errors_total"]
    assert err and any(f.breach for f in err), [f.model_dump() for f in err]

    # latency_spike -> p95 latency breach
    _inject_and_hit("latency_spike", 2)
    time.sleep(8)
    findings = query_anomalies("orders", window, base_url=base_url)
    lat = [f for f in findings if f.metric == "http_request_duration_seconds"]
    assert lat and any(f.breach for f in lat), [f.model_dump() for f in lat]

    # memory_leak -> RSS breach (absolute threshold; ~8MB per /work hit)
    _inject_and_hit("memory_leak", 25)
    time.sleep(8)
    findings = query_anomalies("orders", window, base_url=base_url)
    mem = [f for f in findings if f.metric == "process_resident_memory_bytes"]
    assert mem and any(f.breach for f in mem), [f.model_dump() for f in mem]
