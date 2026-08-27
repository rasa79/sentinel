"""Execute node — run (or dry-run) the approved remediation action (PLAN.md Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.state import AgentState
from sentinel.tools.executor import execute as run_executor


def execute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Execute the approved remediation (dry-run aware, D11)."""
    remediation = state.get("remediation")
    if remediation is None:
        return {"execution": None}
    dry_run = config["configurable"].get("dry_run", True)
    result = run_executor(
        remediation.action, remediation.target_service, remediation.params, dry_run
    )
    return {"execution": result}
