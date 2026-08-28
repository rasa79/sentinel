"""Integration test for the SSE stream (Task 5.4): replay history, tail live, close on terminal.

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
from sentinel.config import Settings, VerificationSettings
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
        "annotations": {"summary": "payments SSE stream test"},
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


async def _cleanup(state: AppState, incident_id: str) -> None:
    with state.session_factory() as session:
        session.query(AgentEvent).filter(AgentEvent.incident_id == uuid.UUID(incident_id)).delete()
        incident = session.get(Incident, uuid.UUID(incident_id))
        if incident is not None:
            session.delete(incident)
        session.commit()


def _parse_frame(lines: list[str]) -> dict[str, Any] | None:
    """Parse one SSE frame into ``{event, data}``; None for comment/heartbeat-only frames."""
    event: str | None = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if not data_lines:
        return None
    try:
        data = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None
    return {"event": event, "data": data}


async def _read_sse(client: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    """Consume an SSE stream to completion, returning the parsed frames it delivered."""
    frames: list[dict[str, Any]] = []
    async with client.stream("GET", url) as resp:
        assert resp.status_code == 200, f"stream returned {resp.status_code}"
        frame_lines: list[str] = []
        async for line in resp.aiter_lines():
            if line == "":
                parsed = _parse_frame(frame_lines)
                frame_lines = []
                if parsed is not None:
                    frames.append(parsed)
            else:
                frame_lines.append(line)
    return frames


async def test_stream_replays_then_tails_and_closes_on_terminal() -> None:
    settings = Settings(_env_file=os.devnull, verification=VerificationSettings(delay_seconds=1))
    state = _make_state(_make_llm(), settings)
    app = create_app(state)
    alertname = f"StreamFlow-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/alerts/webhook", json={"alerts": [_alert(alertname)]})
        assert r.status_code == 202
        incident_id = r.json()["incident_id"]
        await _wait_for(state, incident_id, "awaiting_approval")

        # Connect mid-run: history (triage/hypothesis/remediation) must replay, then it tails live.
        reader = asyncio.create_task(_read_sse(client, f"/incidents/{incident_id}/stream"))
        # Give the reader a moment to subscribe and drain the replay before approving.
        await asyncio.sleep(1.0)
        ar = await client.post(f"/incidents/{incident_id}/approve")
        assert ar.status_code == 202

        # Stream must close on terminal status; don't let a bug hang the test forever.
        frames = await asyncio.wait_for(reader, timeout=30.0)

    events = [f["event"] for f in frames]
    # (a) replay path: the pre-approval nodes arrive as "history" frames.
    assert "history" in events, f"expected replay; got events={events}"
    # (b) live path + no loss: the resume's verify/report arrive as live node_updates.
    assert "node_update" in events, f"expected live node_update; got events={events}"
    # (c) terminal close: the final frame is a run_complete with the resolved status.
    assert frames[-1]["event"] == "run_complete", f"expected run_complete last; got {events}"
    assert frames[-1]["data"]["payload"]["status"] == "resolved"

    await _cleanup(state, incident_id)
