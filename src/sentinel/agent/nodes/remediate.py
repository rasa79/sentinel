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

    allowed_actions = set(settings.remediation.allowed_actions)
    allowed_services = set(settings.remediation.allowed_services)
    threshold = settings.remediation.confidence_threshold
    if proposal.action not in allowed_actions or hypothesis.confidence < threshold:
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
    # A hallucinated target must not reach the executor (LEARN[23]). The LLM can name an endpoint
    # (e.g. the /work route) rather than a service; correct it to the authoritative affected service
    # from the alert, otherwise fall back to no_action so the run still resolves without crashing.
    if proposal.target_service not in allowed_services:
        safe_target = target if target in allowed_services else None
        if safe_target is None:
            proposal = RemediationProposal(
                action="no_action",
                target_service=target,
                params={
                    "original": proposal.action,
                    "target_original": proposal.target_service,
                },
                rationale=(
                    f"rejected: target_service {proposal.target_service!r} not in allowed_services;"
                    f" no known service to target"
                ),
            )
            return {"remediation": proposal, "escalate": True}
        proposal = proposal.model_copy(
            update={
                "target_service": safe_target,
                "rationale": f"{proposal.rationale} (target corrected to {safe_target})",
            }
        )
    return {"remediation": proposal}
