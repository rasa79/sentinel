"""Retrieve matching runbooks via RAG (PLAN.md Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.state import AgentState
from sentinel.rag.retrieve import retrieve_runbooks


async def runbook_rag(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Retrieve runbook hits for the affected service + symptom, to constrain the hypothesis."""
    service = state["alert"].service
    symptom = f"{state['alert'].name} on {service}"
    hits = retrieve_runbooks(symptom, k=3, settings=config["configurable"].get("settings"))
    return {"runbooks": hits}
