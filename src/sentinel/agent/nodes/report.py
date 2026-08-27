"""Report node — build and persist the final IncidentReport (PLAN.md Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import IncidentReport
from sentinel.agent.state import AgentState
from sentinel.llm.structured import structured_call
from sentinel.prompts.report import build_report_prompt


def _incident_summary(state: AgentState) -> str:
    alert = state["alert"]
    hypothesis = state.get("hypothesis")
    remediation = state.get("remediation")
    parts = [f"alert={alert.name} on {alert.service}"]
    if hypothesis:
        parts.append(f"hypothesis={hypothesis.cause} (conf={hypothesis.confidence})")
    if remediation:
        parts.append(f"remediation={remediation.action} on {remediation.target_service}")
    if state.get("approval") is not None:
        parts.append(f"approval={state['approval']}")
    return " | ".join(parts)


async def report(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Produce the final IncidentReport."""
    llm = config["configurable"]["llm"]
    prompt = build_report_prompt(_incident_summary(state))
    result = structured_call(llm, prompt, IncidentReport)
    return {"report": result}
