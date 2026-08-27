"""Integration test for the approval endpoints (Task 5.3): alert -> awaiting_approval -> approve.

Requires the compose stack + DB. Marked ``integration``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from sentinel.api.app import create_app
from sentinel.api.deps import AppState
from sentinel.config import Settings
from sentinel.db.models import AgentEvent, Incident
from sentinel.db.session import create_engine_from_url, make_session_factory

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "llm"


def _load(name: str) -> str:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))["response"]


class RoutingFakeLLM:
    def __init__(self, responses: list[tuple[str, str]]) -> None:
        self._responses = responses

    def invoke(self, prompt: str, **kwargs: object) -> AIMessage:  # noqa: ARG002
        for marker, response in self._responses:
            if marker in prompt:
                return AIMessage(content=response)
        raise AssertionError(f"no LLM response for prompt: {prompt[:100]!r}")


def _make_state(llm: Any, settings: Settings) -> AppState:
    from sentinel.agent.events import EventBus
    from sentinel.agent.graph import build_graph, make_checkpointer

    engine = create_engine_from_url(settings.database.url)
    session_factory = make_session_factory(engine)
    checkpointer = make_checkpointer(settings.database.url)
    graph = build_graph(checkpointer)
    return AppState(
        settings=settings,
        session_factory=session_factory,
        graph=graph,
        event_bus=EventBus(session_factory=session_factory),
        llm=llm,
        checkpointer=checkpointer,
    )


def _make_llm() -> RoutingFakeLLM:
    return RoutingFakeLLM(
        [
            ("Classify the incoming alert", _load("triage_ok.json")),
            ("form a root-cause hypothesis", _load("hypothesis_ok.json")),
            ("propose a single remediation action", _load("remediation_ok.json")),
            ("post-incident reporter", _load("report_ok.json")),
        ]
    )


def _alert(name: str) -> dict[str, Any]:
    return {
        "status": "firing",
        "labels": {
            "alertname": name,
            "service": "payments",
            "severity": "critical",
        },
        "annotations": {"summary": "payments approval-flow test"},
    }


async def _status(state: AppState, incident_id: str) -> str:
    with state.session_factory() as session:
        incident = session.get(Incident, incident_id)
        return incident.status if incident else "missing"


async def _wait_for(state: AppState, incident_id: str, target: str, max_wait: float = 30.0) -> None:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if await _status(state, incident_id) == target:
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"incident {incident_id} never reached {target!r}")


async def _wait_terminal(state: AppState, incident_id: str, max_wait: float = 30.0) -> None:
    terminal = {"resolved", "escalated", "rejected"}
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if await _status(state, incident_id) in terminal:
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"incident {incident_id} never reached a terminal status")


async def _cleanup(state: AppState, incident_id: str) -> None:
    with state.session_factory() as session:
        session.query(AgentEvent).filter(AgentEvent.incident_id == uuid.UUID(incident_id)).delete()
        incident = session.get(Incident, uuid.UUID(incident_id))
        if incident is not None:
            session.delete(incident)
        session.commit()


async def test_approval_flow_end_to_end() -> None:
    settings = Settings(_env_file=os.devnull)
    state = _make_state(_make_llm(), settings)
    app = create_app(state)
    alertname = f"ApprovalFlow-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/alerts/webhook", json={"alerts": [_alert(alertname)]})
        assert r.status_code == 202
        incident_id = r.json()["incident_id"]
        await _wait_for(state, incident_id, "awaiting_approval")

        ar = await client.post(f"/incidents/{incident_id}/approve")
        assert ar.status_code == 202
        await _wait_terminal(state, incident_id)

        gr = await client.get(f"/incidents/{incident_id}")
        body = gr.json()
        # execute ran in dry-run, then verify + report.
        assert body["state"]["execution"]["dry_run"] is True
        assert body["state"]["verification"] is not None
        assert body["state"]["report"]["status"] == "resolved"

        # Approving an already-terminal incident must be a 409.
        r409 = await client.post(f"/incidents/{incident_id}/approve")
        assert r409.status_code == 409

    await _cleanup(state, incident_id)
