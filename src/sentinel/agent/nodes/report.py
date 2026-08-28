"""Report node — build and persist the final IncidentReport (PLAN.md Task 3.3).

The report is the system of record, so its ``status`` and the outcome-critical part of its
``summary`` are DERIVED from the actual execution + verification results, not from the proposed
action. An LLM may elaborate the narrative for a clean resolution, but it must never narrate intent
over a real escalation (the defect: a report said "rolled back" while execution escalated).
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import ExecutionResult, IncidentReport, VerificationResult
from sentinel.agent.state import AgentState
from sentinel.llm.structured import structured_call
from sentinel.prompts.report import build_report_prompt

# Execution statuses that mean the action did NOT actually take effect (D11).
_NON_ACTION_STATUSES = frozenset({"escalated", "not_found", "not_applicable"})


def _derive_status(
    execution: ExecutionResult | None, verification: VerificationResult | None
) -> str:
    """Derive the report status from the ACTUAL outcome, never from the proposed action."""
    if execution is not None and execution.status in _NON_ACTION_STATUSES:
        return "escalated"
    if verification is not None and not verification.resolved:
        return "escalated"
    return "resolved"


def _escalated_summary(
    state: AgentState, execution: ExecutionResult | None, verification: VerificationResult | None
) -> str:
    """Factual summary for a non-resolved outcome (the correctness-critical case)."""
    parts: list[str] = []
    if execution is not None and execution.status in _NON_ACTION_STATUSES:
        detail = execution.message or execution.status
        parts.append(
            f"remediation {execution.action} on {execution.target_service} did NOT complete:"
            f" {detail}"
        )
    elif execution is not None and execution.status == "dry_run":
        parts.append(
            f"remediation {execution.action} on {execution.target_service} was simulated"
            " (dry_run), not actually performed"
        )
    if verification is not None and not verification.resolved:
        parts.append("the alert was not resolved after remediation")
    parts.append("escalated for human review")
    return "; ".join(parts)


def _base_summary(state: AgentState) -> str:
    alert = state["alert"]
    hypothesis = state.get("hypothesis")
    remediation = state.get("remediation")
    parts = [f"alert={alert.name} on {alert.service}"]
    if hypothesis:
        parts.append(f"hypothesis={hypothesis.cause}")
    if remediation:
        parts.append(f"remediation={remediation.action} on {remediation.target_service}")
    return " | ".join(parts)


def _outcome_facts(state: AgentState) -> str:
    execution = state.get("execution")
    verification = state.get("verification")
    parts: list[str] = []
    if execution is not None:
        parts.append(f"execution(status={execution.status}, message={execution.message!r})")
    if verification is not None:
        parts.append(f"verification(resolved={verification.resolved})")
    return " | ".join(parts)


def report(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Produce the final IncidentReport, deriving status/summary from the actual outcome."""
    execution = state.get("execution")
    verification = state.get("verification")
    status = _derive_status(execution, verification)

    # Ground-truth hypothesis + remediation come from the earlier nodes, not the LLM re-narrating.
    hypothesis = state.get("hypothesis")
    remediation = state.get("remediation")

    if status != "resolved":
        # Correctness-critical: never let prose contradict an escalation. Summary is deterministic.
        result = IncidentReport(
            summary=_escalated_summary(state, execution, verification),
            hypothesis=hypothesis,
            remediation=remediation,
            status=status,
        )
        return {"report": result}

    # Clean resolution: let the LLM write a readable summary, but only from the real outcome facts.
    llm = config["configurable"]["llm"]
    facts = _base_summary(state)
    if _outcome_facts(state):
        facts = f"{facts}\nACTUAL OUTCOME: {_outcome_facts(state)}"
    prompt = build_report_prompt(facts)
    result = structured_call(llm, prompt, IncidentReport)
    result = result.model_copy(update={"status": status})
    return {"report": result}
