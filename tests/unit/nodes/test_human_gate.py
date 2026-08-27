"""Tests for the human_gate node's interrupt semantics (PLAN.md Task 3.3)."""

from helpers import make_config

from sentinel.agent.nodes.human_gate import human_gate
from sentinel.agent.schemas import RemediationProposal


def _state(alert) -> dict:
    return {
        "incident_id": "i1",
        "alert": alert,
        "remediation": RemediationProposal(
            action="restart_service", target_service="orders", rationale="r"
        ),
    }


def test_human_gate_approves(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.human_gate.interrupt", lambda payload: {"approved": True}
    )
    update = human_gate(_state(alert), make_config())
    assert update["approval"] is True


def test_human_gate_rejects(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.human_gate.interrupt", lambda payload: {"approved": False}
    )
    update = human_gate(_state(alert), make_config())
    assert update["approval"] is False
