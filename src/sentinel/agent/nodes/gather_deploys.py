"""Gather recent deploy events (PLAN.md Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.state import AgentState
from sentinel.tools.deploys import query_deploys


async def gather_deploys(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Fetch recent deploy events for the affected service."""
    service = state["alert"].service
    deploys = query_deploys(service, limit=20)
    return {"deploys": deploys}
