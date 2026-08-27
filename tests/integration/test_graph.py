"""Integration test for the graph: real Postgres checkpointer + interrupt/resume (PLAN.md Task 3.4).

Requires ``docker compose up -d postgres``. Marked ``integration``.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from sentinel.agent.events import EventBus
from sentinel.agent.graph import build_graph, make_checkpointer
from sentinel.agent.schemas import AlertInfo, DeployEvent, ExecutionResult, MetricFinding
from sentinel.config import Settings
from sentinel.db.models import AgentEvent, Incident
from sentinel.db.session import create_engine_from_url, make_session_factory
from sentinel.rag.retrieve import RunbookHit

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "llm"


def _load(fixture_name: str) -> str:
    return json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))["response"]


class RoutingFakeLLM:
    """Returns a fixture response based on a substring marker in the prompt."""

    def __init__(self, responses: list[tuple[str, str]]) -> None:
        self._responses = responses
        self.calls = 0

    def invoke(self, prompt: str, **kwargs: object) -> AIMessage:  # noqa: ARG002
        self.calls += 1
        for marker, response in self._responses:
            if marker in prompt:
                return AIMessage(content=response)
        raise AssertionError(f"no LLM response for prompt: {prompt[:120]!r}")


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=os.devnull)


def _patch_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_logs.query_logs", lambda service, since, limit=100: []
    )
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_metrics.query_anomalies",
        lambda service, window: [MetricFinding(metric="http_errors_total", value=3.0, breach=True)],
    )
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_deploys.query_deploys",
        lambda service, limit=20: [
            DeployEvent(service=service, version="1.0.1", event="bad_deploy")
        ],
    )
    monkeypatch.setattr(
        "sentinel.agent.nodes.runbook_rag.retrieve_runbooks",
        lambda symptom, k=3, settings=None: [
            RunbookHit(title="bad-deploy-rollback", snippet="s", score=0.9)
        ],
    )
    monkeypatch.setattr(
        "sentinel.agent.nodes.execute.run_executor",
        lambda action, target, params, dry_run: ExecutionResult(
            action=action, target_service=target, dry_run=dry_run, status="ok"
        ),
    )
    monkeypatch.setattr(
        "sentinel.agent.nodes.verify.instant_query",
        lambda expr: [MetricFinding(metric="x", value=0.0, breach=False)],
    )


def test_interrupt_resume_roundtrip_through_real_checkpointer(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = uuid.uuid4()
    engine = create_engine_from_url(settings.database.url)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        session.add(
            Incident(
                id=incident_id,
                alert_name="high-latency",
                service="orders",
                severity="high",
                status="investigating",
                raw_alert={},
            )
        )
        session.commit()

    _patch_tools(monkeypatch)
    llm = RoutingFakeLLM(
        [
            ("Classify the incoming alert", _load("triage_ok.json")),
            ("form a root-cause hypothesis", _load("hypothesis_ok.json")),
            ("propose a single remediation action", _load("remediation_ok.json")),
            ("post-incident reporter", _load("report_ok.json")),
        ]
    )
    config = {
        "configurable": {
            "llm": llm,
            "thread_id": str(incident_id),
            "settings": settings,
            "dry_run": True,
        }
    }
    initial: dict = {
        "incident_id": str(incident_id),
        "alert": AlertInfo(name="high-latency", service="orders", severity="high"),
    }

    # 1. First ainvoke reaches the human_gate interrupt.
    graph = build_graph(make_checkpointer(settings.database.url))
    result = graph.invoke(initial, config)
    assert "__interrupt__" in result, "expected the graph to suspend at human_gate"
    payload = result["__interrupt__"][0].value
    assert payload["proposal"]["action"] == "restart_service"

    # 2. Simulate a process restart: a NEW checkpointer + graph object over the same DB.
    graph2 = build_graph(make_checkpointer(settings.database.url))
    result2 = graph2.invoke(Command(resume={"approved": True}), config)
    assert result2.get("verification") is not None  # verify ran
    assert result2.get("report") is not None  # report reached (resolved)
    assert result2["report"].status == "resolved"

    # 3. EventBus persistence to agent_events (D10).
    bus = EventBus(session_factory=session_factory)
    asyncio.run(bus.emit(str(incident_id), "report", "report_complete", {"status": "resolved"}))
    with session_factory() as session:
        rows = session.query(AgentEvent).filter(AgentEvent.incident_id == incident_id).all()
        assert len(rows) >= 1

    # Cleanup (best-effort) so the test is re-runnable.
    with session_factory() as session:
        session.query(AgentEvent).filter(AgentEvent.incident_id == incident_id).delete()
        incident = session.get(Incident, incident_id)
        if incident is not None:
            session.delete(incident)
        session.commit()
