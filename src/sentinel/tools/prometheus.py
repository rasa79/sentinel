"""Prometheus client interface (returned by nodes; implemented in Phase 4)."""

from __future__ import annotations

from datetime import timedelta

from sentinel.agent.schemas import MetricFinding


def query_anomalies(service: str, window: timedelta) -> list[MetricFinding]:
    """Run the fixed anomaly PromQL suite for ``service`` (implemented in Phase 4)."""
    raise NotImplementedError("Prometheus query_anomalies is implemented in Phase 4")


def instant_query(expr: str) -> list[MetricFinding]:
    """Run a single instant PromQL query (reused by the verify node, D15)."""
    raise NotImplementedError("Prometheus instant_query is implemented in Phase 4")
