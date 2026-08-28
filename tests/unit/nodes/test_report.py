"""Tests for the report node (PLAN.md Task 3.3)."""

from helpers import load_response, make_config

from sentinel.agent.nodes.report import report
from sentinel.agent.schemas import (
    ExecutionResult,
    IncidentReport,
    RemediationProposal,
    RootCauseHypothesis,
    VerificationResult,
)


def test_report_parses_fake_llm(alert) -> None:
    config = make_config(load_response("report_ok.json"))
    update = report({"incident_id": "i1", "alert": alert}, config)
    assert isinstance(update["report"], IncidentReport)
    assert update["report"].status == "resolved"


def test_report_with_rich_state(alert) -> None:
    config = make_config(load_response("report_ok.json"))
    hypothesis = RootCauseHypothesis(
        cause="faulty release", confidence=0.8, evidence=[], affected_service="orders"
    )
    remediation = RemediationProposal(
        action="rollback_deploy", target_service="orders", rationale="r"
    )
    state = {
        "incident_id": "i1",
        "alert": alert,
        "hypothesis": hypothesis,
        "remediation": remediation,
        "approval": True,
    }
    update = report(state, config)
    assert update["report"].status == "resolved"


def test_report_escalated_when_execution_escalated(alert) -> None:
    """Requirement: an execution that escalates must be reported escalated, not 'rolled back'."""
    config = make_config(load_response("report_ok.json"))  # LLM not used on the escalated path
    remediation = RemediationProposal(
        action="rollback_deploy", target_service="orders", rationale="r"
    )
    state = {
        "incident_id": "i1",
        "alert": alert,
        "remediation": remediation,
        "execution": ExecutionResult(
            action="rollback_deploy",
            target_service="orders",
            dry_run=True,
            status="escalated",
            message="no previous deploy version recorded; cannot roll back",
        ),
        "verification": VerificationResult(resolved=False, attempts=1, values=[0.02]),
    }
    update = report(state, config)
    result = update["report"]
    assert result.status == "escalated", f"expected escalated, got {result.status}"
    assert "did NOT complete" in result.summary
    assert "cannot roll back" in result.summary


def test_report_escalated_when_verification_not_resolved(alert) -> None:
    """A simulated remediation that leaves the alert breaching must be reported escalated."""
    config = make_config(load_response("report_ok.json"))
    state = {
        "incident_id": "i1",
        "alert": alert,
        "execution": ExecutionResult(
            action="restart_service",
            target_service="orders",
            dry_run=True,
            status="dry_run",
            message="would restart deploy-orders-1",
        ),
        "verification": VerificationResult(resolved=False, attempts=1, values=[0.04]),
    }
    update = report(state, config)
    result = update["report"]
    assert result.status == "escalated", f"expected escalated, got {result.status}"
    assert "was not resolved" in result.summary
    assert "escalated for human review" in result.summary
