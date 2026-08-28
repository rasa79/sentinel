"""Gather metric anomalies from Prometheus (PLAN.md Task 3.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.evidence import retry_while_empty
from sentinel.agent.schemas import MetricFinding
from sentinel.agent.state import AgentState
from sentinel.tools.prometheus import query_anomalies

# Aligned with the 5s scrape interval (D16) and the demo's short anomaly windows. A longer window
# (e.g. 15m) dilutes a fresh burst down to ~0.009, which still breaches a >0 threshold but weakens
# the signal the hypothesis step reasons about (LEARN[22]).
_WINDOW = timedelta(minutes=5)
_RETRY_ATTEMPTS = 4
_RETRY_INTERVAL = 3.0


def _no_signal(findings: list[MetricFinding]) -> bool:
    """True when nothing breaches — a suspicious-empty result during an active alert (LEARN[28])."""
    return not any(f.breach for f in findings)


def gather_metrics(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Run the fixed anomaly PromQL suite, retrying briefly when no metric breaches (LEARN[28])."""
    service = state["alert"].service

    def probe() -> list[MetricFinding]:
        return query_anomalies(service, window=_WINDOW)

    metrics = retry_while_empty(
        probe, _no_signal, attempts=_RETRY_ATTEMPTS, interval_seconds=_RETRY_INTERVAL
    )
    return {"metrics": metrics}
