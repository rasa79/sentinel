"""Verify node — re-query the alerting expression after remediation (D15)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import VerificationResult
from sentinel.agent.state import AgentState
from sentinel.tools.prometheus import instant_query


async def verify(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Re-check the alerting PromQL expression; resolved if nothing is breaching (D15)."""
    expr = config["configurable"].get("verify_expr", "rate(http_errors_total[5m])")
    findings = instant_query(expr)
    breach = any(f.breach for f in findings)
    resolved = not breach
    return {
        "verification": VerificationResult(
            resolved=resolved,
            attempts=1,
            values=[f.value for f in findings],
        )
    }
