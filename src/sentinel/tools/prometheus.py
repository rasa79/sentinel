# LEARN[22]: PromQL-specific notes — rate(), histogram quantiles, empty results (QS-4 cross-ref)
# Why this way: this client reuses the retry policy from the Loki client (LEARN[21]) and adds only
#    PromQL-specific teaching. The anomaly suite runs a few fixed PromQL expressions and maps each
#   to a
#   MetricFinding with a breach flag.
# Good sides:
#   - the agent sees real, named signals (error rate, p95, RSS) rather than a raw query string
#   - an empty query result is a finding with breach=False, never an exception (absence of signal)
#   - one retry policy shared with Loki (LEARN[21]) keeps the transient-failure handling consistent
# Drawbacks:
#   - fixed expressions are tuned for the demo chaos; a real fleet needs per-service thresholds
#   - thresholds are hard-coded (error>0, p95>1s, RSS>180MB), which is a blunt instrument
#   - a window dilutes a fresh burst: rate()[15m] lowers a brand-new spike to ~0.009, so the gather
#     nodes use a short 5m window aligned with the 5s scrape (D16); the threshold stays >0 because
#     the alert already established that errors are happening, so ANY positive rate confirms (not
#     discovers) the incident.
#  Concept: three PromQL ideas matter here. (1) rate() over a Counter turns a monotonic counter into
# a
#    per-second rate, so "errors happening now" is rate(http_errors_total[2m]), not the counter
#   itself
#   (the counter only ever grows). (2) histogram_quantile computes an approximate quantile from a
#   Histogram's _bucket series — p95 latency is
#    histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])). (3) an empty query
#   result
#   is DATA, not an error: it means the series does not exist / has no samples in the window, and we
#   express that as a finding with breach=False so the caller can reason about "no signal" without
#    catching exceptions. This mirrors how an SRE reads a dashboard: an absent series is a valid
#   state to
#    inspect, not a crash. The Memory gauge (process_resident_memory_bytes) is a Gauge, which can go
#   up
#   and down, so we breach on an absolute threshold rather than a rate.
# See also: LEARN[21] (retry policy, shared), LEARN[28] (empty-is-suspicious retry the gather
# nodes add — the client here is still empty-as-data), D9 in PLAN.md
from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from sentinel.agent.schemas import MetricFinding
from sentinel.config import Settings
from sentinel.tools.loki import _get_json

_MEMORY_THRESHOLD = 180 * 1024 * 1024  # ~180MB RSS breach floor for the demo containers
_P95_THRESHOLD_SECONDS = 1.0
_ERROR_THRESHOLD = 0.0


def _promql_duration(window: timedelta) -> str:
    secs = int(window.total_seconds())
    if secs % 3600 == 0:
        return f"{secs // 3600}h"
    if secs % 60 == 0:
        return f"{secs // 60}m"
    return f"{secs}s"


def _metric_from_expr(expr: str) -> str:
    if "http_errors_total" in expr:
        return "http_errors_total"
    if "http_request_duration_seconds" in expr:
        return "http_request_duration_seconds"
    if "process_resident_memory_bytes" in expr:
        return "process_resident_memory_bytes"
    return expr


def _breach(expr: str, value: float) -> bool:
    if "http_errors_total" in expr:
        return value > _ERROR_THRESHOLD
    if "http_request_duration_seconds" in expr:
        return value > _P95_THRESHOLD_SECONDS
    if "process_resident_memory_bytes" in expr:
        return value > _MEMORY_THRESHOLD
    return value > 0.0


def _query(client: httpx.Client, base_url: str, expr: str) -> list[dict[str, Any]]:
    payload = _get_json(client, f"{base_url.rstrip('/')}/api/v1/query", {"query": expr})
    return list(payload.get("data", {}).get("result", []))


def instant_query(
    expr: str,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> list[MetricFinding]:
    """Run an instant PromQL query and return MetricFindings with a breach flag (D15/verify)."""
    base_url = base_url or Settings().prometheus.url
    client = client or httpx.Client(timeout=5.0)
    findings: list[MetricFinding] = []
    for result in _query(client, base_url, expr):
        value = float(result["value"][1])
        findings.append(
            MetricFinding(
                metric=_metric_from_expr(expr),
                value=value,
                breach=_breach(expr, value),
                expression=expr,
            )
        )
    return findings


def query_anomalies(
    service: str,
    window: timedelta,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> list[MetricFinding]:
    """Run the fixed anomaly PromQL suite for ``service`` (D9)."""
    base_url = base_url or Settings().prometheus.url
    client = client or httpx.Client(timeout=5.0)
    dur = _promql_duration(window)

    expressions = [
        f'rate(http_errors_total{{service="{service}"}}[{dur}])',
        f'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{{service="{service}"}}'
        f"[{dur}]))",
        f'process_resident_memory_bytes{{instance=~"{service}:.*"}}',
    ]

    findings: list[MetricFinding] = []
    for expr in expressions:
        results = _query(client, base_url, expr)
        if not results:
            # Empty result is DATA (absence of signal), not an error (LEARN[22]).
            findings.append(
                MetricFinding(
                    metric=_metric_from_expr(expr), value=0.0, breach=False, expression=expr
                )
            )
            continue
        for result in results:
            value = float(result["value"][1])
            findings.append(
                MetricFinding(
                    metric=_metric_from_expr(expr),
                    value=value,
                    breach=_breach(expr, value),
                    expression=expr,
                )
            )
    return findings
