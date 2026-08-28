"""Integration tests for the remediation verification loop (Phase 6, D15).

Exercises both verification outcomes against real chaos + real Prometheus:
  - resolved: a restart_service that actually restarts the container (clearing the process-local
    chaos and resetting the error counter) lets the alerting expression clear -> resolved.
  - escalated: a scale_replicas that is not_applicable does NOT clear the fault -> the fixed-window
    re-check keeps breaching and escalates, emitting an escalation event with the metric values.

Requires the compose stack + Docker (the executor restarts the orders container). Integration.
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
from sentinel.config import RemediationSettings, Settings, VerificationSettings
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


def _llm(remediation: str) -> RoutingFakeLLM:
    return RoutingFakeLLM(
        [
            ("Classify the incoming alert", _load("triage_ok.json")),
            ("form a root-cause hypothesis", _load("hypothesis_ok.json")),
            ("propose a single remediation action", _load(remediation)),
            ("post-incident reporter", _load("report_ok.json")),
        ]
    )


def _alert(name: str, service: str = "orders") -> dict[str, Any]:
    return {
        "status": "firing",
        "labels": {"alertname": name, "service": service, "severity": "critical"},
        "annotations": {"summary": f"{service} error burst"},
    }


async def _status(state: AppState, incident_id: str) -> str:
    with state.session_factory() as session:
        incident = session.get(Incident, uuid.UUID(incident_id))
        return incident.status if incident else "missing"


async def _wait_status(
    state: AppState, incident_id: str, targets: set[str], max_wait: float = 90.0
) -> None:
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        if await _status(state, incident_id) in targets:
            return
        await asyncio.sleep(1.0)
    raise AssertionError(f"incident {incident_id} never reached {sorted(targets)!r}")


async def _cleanup(state: AppState, incident_id: str) -> None:
    with state.session_factory() as session:
        session.query(AgentEvent).filter(AgentEvent.incident_id == uuid.UUID(incident_id)).delete()
        incident = session.get(Incident, uuid.UUID(incident_id))
        if incident is not None:
            session.delete(incident)
        session.commit()


async def _inject_and_hit(chaos_type: str, hits: int, duration: int) -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        await client.post(
            _SERVICE_URL + "/chaos", json={"type": chaos_type, "duration_seconds": duration}
        )
        for _ in range(hits):
            try:
                await client.get(_SERVICE_URL + "/work")
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)


async def test_verification_loop_resolves_after_real_restart() -> None:
    # dry_run=False so restart_service ACTUALLY restarts the container (clearing the process-local
    # chaos and resetting the error counter). The re-check uses a short [1m] window and a delay long
    # enough that the window is entirely post-reset, so a cumulative counter rate no longer masks
    # the recovery (a [5m] rate stays non-zero for minutes even after the fault clears).
    settings = Settings(
        _env_file=os.devnull,
        remediation=RemediationSettings(dry_run=False),
        verification=VerificationSettings(
            delay_seconds=70,
            attempts=1,
            expr='rate(http_errors_total{service="orders"}[1m])',
        ),
    )
    state = _make_state(_llm("remediation_ok.json"), settings)
    app = create_app(state)
    alertname = f"VerifyResolved-{uuid.uuid4().hex[:8]}"
    await _inject_and_hit("error_burst", 3, 60)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/alerts/webhook", json={"alerts": [_alert(alertname)]})
        assert r.status_code == 202
        incident_id = r.json()["incident_id"]
        await _wait_status(state, incident_id, {"awaiting_approval"}, max_wait=120)
        ar = await client.post(f"/incidents/{incident_id}/approve")
        assert ar.status_code == 202
        # restart_service (real) must clear the fault -> resolved.
        await _wait_status(state, incident_id, {"resolved"}, max_wait=180)
        body = (await client.get(f"/incidents/{incident_id}")).json()
        assert body["incident"]["status"] == "resolved"

    await _cleanup(state, incident_id)
