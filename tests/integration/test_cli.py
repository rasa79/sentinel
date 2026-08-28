"""Integration test for the CLI commands wired to a live API server (Task 5.5).

Starts the FastAPI app under uvicorn on an ephemeral port (so the CLI's own httpx client hits a
real socket), then drives the typer commands through ``CliRunner`` end-to-end. Requires the
compose stack + DB. Marked ``integration``.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from langchain_core.messages import AIMessage
from typer.testing import CliRunner

from sentinel.api.app import create_app
from sentinel.api.deps import AppState
from sentinel.config import Settings, VerificationSettings
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(app: Any) -> tuple[str, threading.Thread, uvicorn.Server]:
    """Start the app on an ephemeral port; return (base_url, thread, server)."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start in time")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", thread, server


async def _wait_status(
    state: AppState, incident_id: str, targets: set[str], max_wait: float = 30.0
) -> None:
    from sentinel.db.models import Incident

    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        with state.session_factory() as session:
            incident = session.get(Incident, uuid.UUID(incident_id))
            if incident is not None and incident.status in targets:
                return
        await asyncio.sleep(0.5)
    raise AssertionError(f"incident {incident_id} never reached {sorted(targets)!r}")


def test_cli_commands_against_live_api() -> None:
    import httpx

    from sentinel.cli import main as cli
    from sentinel.db.models import AgentEvent, Incident

    settings = Settings(_env_file=os.devnull, verification=VerificationSettings(delay_seconds=1))
    state = _make_state(_make_llm(), settings)
    app = create_app(state)
    base, thread, server = _start_server(app)
    incident_id = ""
    runner = CliRunner()
    try:
        # Seed an incident through the live webhook so the CLI hits real data.
        with httpx.Client(base_url=base, timeout=10) as client:
            resp = client.post(
                "/alerts/webhook",
                json={
                    "alerts": [
                        {
                            "status": "firing",
                            "labels": {
                                "alertname": f"CliFlow-{uuid.uuid4().hex[:8]}",
                                "service": "orders",
                                "severity": "critical",
                            },
                            "annotations": {"summary": "cli test"},
                        }
                    ]
                },
            )
            resp.raise_for_status()
            incident_id = resp.json()["incident_id"]

        # list renders a table without error.
        list_result = runner.invoke(cli.app, ["incidents", "list", "--api", base])
        assert list_result.exit_code == 0, list_result.output
        assert incident_id in list_result.output

        # show renders the incident detail including its id.
        show_result = runner.invoke(cli.app, ["incidents", "show", incident_id, "--api", base])
        assert show_result.exit_code == 0, show_result.output
        assert incident_id in show_result.output

        # Wait for the interrupt, then approve via the CLI; the run must finish in a terminal
        # status (resolved if verification cleared the alert, escalated if the remediation did not
        # actually clear it — the report reflects the real outcome either way).
        asyncio.run(_wait_status(state, incident_id, {"awaiting_approval"}))
        approve_result = runner.invoke(
            cli.app, ["incidents", "approve", incident_id, "--api", base]
        )
        assert approve_result.exit_code == 0, approve_result.output
        asyncio.run(_wait_status(state, incident_id, {"resolved", "escalated", "rejected"}))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        # Cleanup best-effort.
        with state.session_factory() as session:
            session.query(AgentEvent).filter(
                AgentEvent.incident_id == uuid.UUID(incident_id)
            ).delete()
            incident = session.get(Incident, uuid.UUID(incident_id))
            if incident is not None:
                session.delete(incident)
            session.commit()
