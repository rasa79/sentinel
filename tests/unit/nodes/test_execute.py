"""Tests for the execute node (PLAN.md Task 3.3)."""

from helpers import make_config

from sentinel.agent.nodes.execute import execute
from sentinel.agent.schemas import ExecutionResult, RemediationProposal


def _state(alert) -> dict:
    return {
        "incident_id": "i1",
        "alert": alert,
        "remediation": RemediationProposal(
            action="restart_service", target_service="orders", rationale="r"
        ),
    }


async def test_execute_calls_executor_with_dry_run(alert, monkeypatch) -> None:
    calls: list[tuple] = []

    def _run(action, target, params, dry_run):
        calls.append((action, target, dry_run))
        return ExecutionResult(action=action, target_service=target, dry_run=dry_run, status="ok")

    monkeypatch.setattr("sentinel.agent.nodes.execute.run_executor", _run)
    update = await execute(_state(alert), make_config(dry_run=True))
    assert update["execution"].dry_run is True
    assert calls[0] == ("restart_service", "orders", True)


async def test_execute_no_remediation(alert) -> None:
    update = await execute({"incident_id": "i1", "alert": alert}, make_config())
    assert update["execution"] is None
