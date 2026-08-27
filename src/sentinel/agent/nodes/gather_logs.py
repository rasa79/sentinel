"""Gather log excerpts from Loki (PLAN.md Task 3.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.state import AgentState
from sentinel.tools.loki import query_logs


def gather_logs(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Fetch recent log lines for the affected service."""
    service = state["alert"].service
    logs = query_logs(service, since=timedelta(minutes=15), limit=100)
    return {"logs": logs}
