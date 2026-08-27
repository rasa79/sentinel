"""Tests for the runbook_rag node (PLAN.md Task 3.3)."""

from helpers import make_config

from sentinel.agent.nodes.runbook_rag import runbook_rag
from sentinel.rag.retrieve import RunbookHit


async def test_runbook_rag_happy_path(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.runbook_rag.retrieve_runbooks",
        lambda symptom, k=3, settings=None: [
            RunbookHit(title="latency-spike-downstream", snippet="s", score=0.9)
        ],
    )
    update = await runbook_rag({"incident_id": "i1", "alert": alert}, make_config())
    assert update["runbooks"][0].title == "latency-spike-downstream"


async def test_runbook_rag_empty_result(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.runbook_rag.retrieve_runbooks", lambda symptom, k=3, settings=None: []
    )
    update = await runbook_rag({"incident_id": "i1", "alert": alert}, make_config())
    assert update["runbooks"] == []
