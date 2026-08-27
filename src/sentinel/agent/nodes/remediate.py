"""Remediation node — propose an action and enforce the whitelist + confidence floor (Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import RemediationProposal, RootCauseHypothesis
from sentinel.agent.state import AgentState
from sentinel.config import Settings
from sentinel.llm.structured import structured_call
from sentinel.prompts.remediate import build_remediation_prompt


def _hypothesis_summary(hypothesis: RootCauseHypothesis) -> str:
    lines = [f"cause={hypothesis.cause}", f"confidence={hypothesis.confidence}"]
    if hypothesis.affected_service:
        lines.append(f"service={hypothesis.affected_service}")
    if hypothesis.references:
        lines.append("references=" + "; ".join(hypothesis.references))
    return " | ".join(lines)


def remediate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Propose remediation; enforce whitelist + confidence floor (else no_action + escalate)."""
    llm = config["configurable"]["llm"]
    settings = config["configurable"].get("settings") or Settings()
    target = state["alert"].service

    hypothesis = state.get("hypothesis")
    if hypothesis is None:
        return {
            "remediation": RemediationProposal(
                action="no_action", target_service=target, rationale="no hypothesis produced"
            ),
            "escalate": True,
        }

    proposal = structured_call(
        llm, build_remediation_prompt(_hypothesis_summary(hypothesis)), RemediationProposal
    )

    allowed = set(settings.remediation.allowed_actions)
    threshold = settings.remediation.confidence_threshold
    if proposal.action not in allowed or hypothesis.confidence < threshold:
        proposal = RemediationProposal(
            action="no_action",
            target_service=target,
            params={"original": proposal.action, "confidence": hypothesis.confidence},
            rationale=(
                f"rejected: action {proposal.action!r} not in whitelist or confidence "
                f"{hypothesis.confidence} < {threshold}"
            ),
        )
        return {"remediation": proposal, "escalate": True}
    return {"remediation": proposal}
