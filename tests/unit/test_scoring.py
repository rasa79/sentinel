"""Tests for eval scoring (PLAN.md Task 7.2 / D13)."""

from __future__ import annotations

from sentinel.agent.schemas import RemediationProposal, RootCauseHypothesis
from sentinel.evals.dataset import KnownCause
from sentinel.evals.scoring import categorize_cause, score_hypothesis, score_remediation


def test_categorize_cause_maps_synonyms() -> None:
    assert categorize_cause("An error burst is occurring on orders") == "error_burst"
    assert categorize_cause("users see high latency") == "latency_spike"
    assert categorize_cause("resident memory is climbing") == "memory_leak"
    assert categorize_cause("a bad deploy was released") == "bad_deploy"
    assert categorize_cause("the service is healthy") is None


def test_categorize_cause_prioritizes_specific_fault() -> None:
    # A deploy-correlated error burst must NOT be bucketed as bad_deploy just for mentioning one.
    assert categorize_cause("error burst after a deploy") == "error_burst"
    assert categorize_cause("bad deploy caused errors") == "bad_deploy"


def _hyp(cause: str, service: str) -> RootCauseHypothesis:
    return RootCauseHypothesis(cause=cause, confidence=0.9, evidence=[], affected_service=service)


def test_score_hypothesis_matches_service_and_category() -> None:
    known = KnownCause(category="error_burst", affected_service="orders")
    assert score_hypothesis(_hyp("An error burst", "orders"), known)
    # wrong service
    assert not score_hypothesis(_hyp("An error burst", "payments"), known)
    # wrong category
    assert not score_hypothesis(_hyp("high latency", "orders"), known)


def test_score_remediation_matches_action() -> None:
    r = RemediationProposal(action="rollback_deploy", target_service="orders", rationale="r")
    assert score_remediation(r, "rollback_deploy")
    assert not score_remediation(r, "restart_service")
    assert not score_remediation(None, "rollback_deploy")
