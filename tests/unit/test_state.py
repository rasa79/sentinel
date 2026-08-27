"""Unit tests for the agent state and strict schemas (PLAN.md Task 3.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel.agent.schemas import RemediationProposal, RootCauseHypothesis, TriageResult
from sentinel.agent.state import AgentState


def test_state_keys_match_spec() -> None:
    expected = {
        "incident_id",
        "alert",
        "triage",
        "logs",
        "metrics",
        "deploys",
        "runbooks",
        "hypothesis",
        "remediation",
        "approval",
        "execution",
        "verification",
        "report",
        "errors",
        "escalate",
    }
    assert set(AgentState.__annotations__) == expected


def test_state_accepts_a_partial_update() -> None:
    state: AgentState = {"incident_id": "inc-1", "errors": []}
    state["triage"] = TriageResult(category="latency", summary="slow", severity="high")
    assert state["triage"].category == "latency"


def test_llm_schemas_forbid_extra_keys() -> None:
    """extra='forbid' (LEARN[15]) rejects hallucinated keys on every LLM-facing schema."""
    with pytest.raises(ValidationError):
        RootCauseHypothesis(
            cause="x", confidence=0.5, evidence=[], affected_service="orders", bogus_field=1
        )
    with pytest.raises(ValidationError):
        RemediationProposal(
            action="restart_service", target_service="orders", rationale="r", bogus_field=1
        )
    with pytest.raises(ValidationError):
        TriageResult(category="x", summary="s", severity="high", bogus_field=1)


def test_hypothesis_validates_confidence_range() -> None:
    with pytest.raises(ValidationError):
        RootCauseHypothesis(cause="x", confidence=1.5, evidence=[], affected_service="orders")
