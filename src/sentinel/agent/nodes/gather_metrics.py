"""Gather metric anomalies from Prometheus (PLAN.md Task 3.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.state import AgentState
from sentinel.tools.prometheus import query_anomalies


async def gather_metrics(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Run the fixed anomaly PromQL suite for the affected service."""
    service = state["alert"].service
    metrics = query_anomalies(service, window=timedelta(minutes=15))
    return {"metrics": metrics}
