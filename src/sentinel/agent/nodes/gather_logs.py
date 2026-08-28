"""Gather log excerpts from Loki (PLAN.md Task 3.3)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.evidence import retry_while_empty
from sentinel.agent.schemas import LogExcerpt
from sentinel.agent.state import AgentState
from sentinel.tools.loki import query_logs

_WINDOW = timedelta(minutes=5)
_RETRY_ATTEMPTS = 4
_RETRY_INTERVAL = 3.0


def gather_logs(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Fetch recent log lines for the affected service, retrying briefly while they are empty."""
    service = state["alert"].service

    def probe() -> list[LogExcerpt]:
        return query_logs(service, since=_WINDOW, limit=100)

    logs = retry_while_empty(
        probe, lambda lines: not lines, attempts=_RETRY_ATTEMPTS, interval_seconds=_RETRY_INTERVAL
    )
    return {"logs": logs}
