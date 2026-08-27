"""Tests for the report node (PLAN.md Task 3.3)."""

from helpers import load_response, make_config

from sentinel.agent.nodes.report import report
from sentinel.agent.schemas import IncidentReport, RemediationProposal, RootCauseHypothesis


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
