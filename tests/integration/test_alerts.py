"""Integration test for the alert webhook (Task 5.1): create + dedupe + graph start.

Requires the compose stack + DB. Marked ``integration``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from sentinel.api.app import create_app
from sentinel.api.deps import AppState
from sentinel.config import Settings
from sentinel.db.models import Incident
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
    graph = build_graph(make_checkpointer(settings.database.url))
    return AppState(
        settings=settings,
        session_factory=session_factory,
        graph=graph,
        event_bus=EventBus(session_factory=session_factory),
        llm=llm,
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


def _alert(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "firing",
        "labels": {"alertname": "HighErrorRate", "service": "orders", "severity": "critical"},
        "annotations": {"summary": "orders error rate high"},
    }


async def _status(state: AppState, incident_id: str) -> str:
    with state.session_factory() as session:
        incident = session.get(Incident, incident_id)
        return incident.status if incident else "missing"


async def test_webhook_creates_dedupes_and_runs_graph() -> None:
    settings = Settings(_env_file=os.devnull)
    state = _make_state(_make_llm(), settings)
    app = create_app(state)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r1 = await client.post("/alerts/webhook", json={"alerts": [_alert()]})
        assert r1.status_code == 202
        id1 = r1.json()["incident_id"]

        # Dedupe: a duplicate alertname+service reuses the incident.
        r2 = await client.post("/alerts/webhook", json={"alerts": [_alert()]})
        assert r2.status_code == 202
        assert r2.json()["incident_id"] == id1

    # The background graph run should reach the human_gate interrupt -> awaiting_approval.
    reached = False
    for _ in range(30):
        await asyncio.sleep(0.5)
        if await _status(state, id1) == "awaiting_approval":
            reached = True
            break
    assert reached, "graph did not reach awaiting_approval"
