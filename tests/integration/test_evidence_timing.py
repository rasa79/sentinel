"""Regression test for evidence timing (PLAN.md Phase 5 defect, iteration 3).

Injects a fault, fires the alert IMMEDIATELY (while the observability pipelines are still lagging),
and asserts the agent does NOT conclude a false alarm while the fault is active: the gather nodes
must retry on empty evidence (LEARN[28]) and observe the error rate + error logs. Requires the
compose stack. Marked ``integration``.
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
_SERVICE_URL = "http://localhost:9001"


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
        "labels": {"alertname": name, "service": "orders", "severity": "critical"},
        "annotations": {"summary": "orders bad-deploy error burst"},
    }


async def _status(state: AppState, incident_id: str) -> str:
    with state.session_factory() as session:
        incident = session.get(Incident, uuid.UUID(incident_id))
        return incident.status if incident else "missing"


async def _wait_status(
    state: AppState, incident_id: str, target: str, max_wait: float = 90.0
) -> None:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if await _status(state, incident_id) == target:
            return
        await asyncio.sleep(1.0)
    raise AssertionError(f"incident {incident_id} never reached {target!r}")


async def _cleanup(state: AppState, incident_id: str) -> None:
    with state.session_factory() as session:
        session.query(AgentEvent).filter(AgentEvent.incident_id == uuid.UUID(incident_id)).delete()
        incident = session.get(Incident, uuid.UUID(incident_id))
        if incident is not None:
            session.delete(incident)
        session.commit()


async def test_agent_does_not_conclude_false_alarm_while_fault_active() -> None:
    settings = Settings(_env_file=os.devnull)
    state = _make_state(_make_llm(), settings)
    app = create_app(state)
    alertname = f"EvidenceTiming-{uuid.uuid4().hex[:8]}"
    incident_id = ""

    # 1. Inject the bad_deploy fault on the orders service.
    async with httpx.AsyncClient(base_url=_SERVICE_URL, timeout=10) as svc:
        await svc.post("/chaos", json={"type": "bad_deploy", "duration_seconds": 60})

    # 2. Fire a short, sparse burst of /work so the fault manifests as 503s (error logs + error
    #    counter) while the graph gathers. It must stay SMALL — a continuous flood would bury the
    #    latency_spike assertion in the shared duration histogram (LEARN[22]).

    async def _burst() -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            for _ in range(5):
                try:
                    await client.get(f"{_SERVICE_URL}/work")
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1.0)

    burst_task = asyncio.create_task(_burst())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 3. Fire the webhook IMMEDIATELY — no settle wait. The fault is active but the metric/log
        #    pipelines have not necessarily caught up.
        r = await client.post("/alerts/webhook", json={"alerts": [_alert(alertname)]})
        assert r.status_code == 202
        incident_id = r.json()["incident_id"]

        # 4. Let the graph reach the actionable human gate (proves it did NOT call this a false
        #    alarm / no_action). The gather retry (LEARN[28]) rides out the lag.
        await _wait_status(state, incident_id, "awaiting_approval")

        burst_task.cancel()
        try:
            await burst_task
        except asyncio.CancelledError:
            pass

        # 5. The gathered evidence must be non-empty: an error-rate breach and real error logs.
        body = (await client.get(f"/incidents/{incident_id}")).json()
        events = body["events"]
        node_names = [e["node"] for e in events]
        assert "gather_metrics" in node_names, f"graph never reached gather_metrics: {node_names}"
        assert "gather_logs" in node_names, f"graph never reached gather_logs: {node_names}"
        metrics_event = next(e for e in events if e["node"] == "gather_metrics")
        err_findings = [
            m for m in metrics_event["payload"]["metrics"] if m["metric"] == "http_errors_total"
        ]
        assert any(m["breach"] for m in err_findings), (
            f"expected an error-rate breach: {err_findings}"
        )
        logs_event = next(e for e in events if e["node"] == "gather_logs")
        assert logs_event["payload"]["logs"], "expected non-empty error log evidence"

    await _cleanup(state, incident_id)
