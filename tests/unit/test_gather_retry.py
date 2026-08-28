"""Deterministic regression test for the evidence-timing gather retry (LEARN[28]).

The gather nodes must NOT take an empty/no-signal result at face value while an active alert's
observability pipeline is still catching up (Prometheus 5s scrape, Loki push lag). This test drives
the gather nodes with a MOCKED evidence source that returns empty first and populated on retry, and
asserts they retry and end with non-empty evidence. It is fully deterministic — it does not depend
on real scrape/push timing, unlike the old integration test which only passed on a warm pipeline.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sentinel.agent.nodes.gather_logs import gather_logs
from sentinel.agent.nodes.gather_metrics import gather_metrics
from sentinel.agent.schemas import AlertInfo, LogExcerpt, MetricFinding


def _state() -> dict[str, Any]:
    return {"alert": AlertInfo(name="x", service="orders", severity="critical", raw={})}


def _no_breach(expr: str) -> list[MetricFinding]:
    """A suspicious-empty metric result: no breach flag (LEARN[28])."""
    return [MetricFinding(metric="http_errors_total", value=0.0, breach=False, expression=expr)]


def _breach(expr: str) -> list[MetricFinding]:
    return [MetricFinding(metric="http_errors_total", value=0.04, breach=True, expression=expr)]


def test_gather_metrics_retries_until_it_sees_a_breach(monkeypatch: Any) -> None:
    calls = {"n": 0}

    def fake_query(service: str, window: timedelta, *a: Any, **kw: Any) -> list[MetricFinding]:
        calls["n"] += 1
        expr = f'rate(http_errors_total{{service="{service}"}}[{window.total_seconds():.0f}m])'
        return _no_breach(expr) if calls["n"] == 1 else _breach(expr)

    monkeypatch.setattr("sentinel.agent.nodes.gather_metrics.query_anomalies", fake_query)
    # No real 3s sleeps: the retry loop should complete instantly in the test.
    monkeypatch.setattr("sentinel.agent.evidence.time.sleep", lambda s: None)

    result = gather_metrics(_state(), {})
    # It retried (queried more than once) and ended with a breach (non-empty evidence).
    assert calls["n"] >= 2, f"expected >=2 queries, got {calls['n']}"
    assert result["metrics"][0].breach is True


def test_gather_logs_retries_until_it_sees_logs(monkeypatch: Any) -> None:
    calls = {"n": 0}

    def fake_query(service: str, since: timedelta, *a: Any, **kw: Any) -> list[LogExcerpt]:
        calls["n"] += 1
        return (
            [] if calls["n"] == 1 else [LogExcerpt(service=service, message="503", level="ERROR")]
        )

    monkeypatch.setattr("sentinel.agent.nodes.gather_logs.query_logs", fake_query)
    monkeypatch.setattr("sentinel.agent.evidence.time.sleep", lambda s: None)

    result = gather_logs(_state(), {})
    assert calls["n"] >= 2, f"expected >=2 queries, got {calls['n']}"
    assert result["logs"] and result["logs"][0].level == "ERROR"
