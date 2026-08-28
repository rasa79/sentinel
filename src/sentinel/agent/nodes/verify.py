"""Verify node — re-query the alerting expression after remediation (D15)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import VerificationResult
from sentinel.agent.state import AgentState
from sentinel.tools.prometheus import instant_query


def verify(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Re-check the alerting expression; resolved if nothing is breaching (D15)."""
    # The expression must be for the incident's own service — a global `rate(...[5m])` placeholder
    # stays non-zero whenever ANY service has recent errors, which would make a genuinely-affected
    # service look unresolved (and vice versa). Default to the affected service's error rate.
    service = state["alert"].service
    expr = config["configurable"].get("verify_expr") or (
        f'rate(http_errors_total{{service="{service}"}}[5m])'
    )
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
