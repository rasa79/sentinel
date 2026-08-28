"""Regression test for the evidence-timing gather retry against the living graph (Phase 5 defect).

Fires the alert through the API IMMEDIATELY and runs the real graph + checkpointer, but uses a
MOCKED evidence source (first query empty, retry non-empty) so the test is deterministic — it does
not depend on real Prometheus scrape / Loki push timing, which made the previous version pipeline-
state-lucky. It asserts both gather nodes ALWAYS run (unconditional gather path) and the graph
reaches the actionable human gate (NOT a false-alarm/no_action conclusion). Requires the compose DB.
Marked ``integration``.
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
        "labels": {"alertname": name, "service": "orders", "severity": "critical"},
        "annotations": {"summary": "orders bad-deploy error burst"},
    }


async def _status(state: AppState, incident_id: str) -> str:
    with state.session_factory() as session:
        incident = session.get(Incident, uuid.UUID(incident_id))
        return incident.status if incident else "missing"


async def _wait_status(
    state: AppState, incident_id: str, target: str, max_wait: float = 60.0
) -> None:
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


async def test_gather_nodes_run_and_no_false_alarm(monkeypatch: Any) -> None:
    from datetime import timedelta

    from sentinel.agent.schemas import LogExcerpt, MetricFinding

    settings = Settings(_env_file=os.devnull)
    state = _make_state(_make_llm(), settings)
    app = create_app(state)

    # Deterministic evidence: the gather nodes see an empty/no-signal result first (as if the
    # pipeline hasn't caught up), then a populated one on retry. Only the first query is empty.
    metric_calls = {"n": 0}
    log_calls = {"n": 0}

    def fake_metrics(service: str, window: timedelta, *a: Any, **kw: Any) -> list[MetricFinding]:
        metric_calls["n"] += 1
        expr = f'rate(http_errors_total{{service="{service}"}}[{window.total_seconds():.0f}m])'
        if metric_calls["n"] == 1:
            return [
                MetricFinding(metric="http_errors_total", value=0.0, breach=False, expression=expr)
            ]
        return [MetricFinding(metric="http_errors_total", value=0.04, breach=True, expression=expr)]

    def fake_logs(service: str, since: timedelta, *a: Any, **kw: Any) -> list[LogExcerpt]:
        log_calls["n"] += 1
        return (
            []
            if log_calls["n"] == 1
            else [LogExcerpt(service=service, message="503", level="ERROR")]
        )

    monkeypatch.setattr("sentinel.agent.nodes.gather_metrics.query_anomalies", fake_metrics)
    monkeypatch.setattr("sentinel.agent.nodes.gather_logs.query_logs", fake_logs)
    # No real 3s sleeps in the retry loop during the test.
    monkeypatch.setattr("sentinel.agent.evidence.time.sleep", lambda s: None)

    alertname = f"EvidenceTiming-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/alerts/webhook", json={"alerts": [_alert(alertname)]})
        assert r.status_code == 202
        incident_id = r.json()["incident_id"]

        # The graph must reach the actionable human gate (NOT a false-alarm / no_action).
        await _wait_status(state, incident_id, "awaiting_approval")

        body = (await client.get(f"/incidents/{incident_id}")).json()
        events = body["events"]
        node_names = [e["node"] for e in events]
        # BOTH gather nodes always run (unconditional gather path, LEARN[28]).
        assert "gather_logs" in node_names, f"gather_logs missing (e2e): {node_names}"
        assert "gather_metrics" in node_names, f"gather_metrics missing (e2e): {node_names}"
        assert "gather_deploys" in node_names, f"gather_deploys missing (e2e): {node_names}"

        # The gather retried (first query empty) and ended with a breach + logs.
        metrics_event = next(e for e in events if e["node"] == "gather_metrics")
        err = [m for m in metrics_event["payload"]["metrics"] if m["metric"] == "http_errors_total"]
        assert any(m["breach"] for m in err), f"expected a breach after retry: {err}"
        logs_event = next(e for e in events if e["node"] == "gather_logs")
        assert logs_event["payload"]["logs"], "expected non-empty log evidence after retry"

        assert metric_calls["n"] >= 2, (
            f"expected gather_metrics to retry, got {metric_calls['n']} call(s)"
        )
        assert log_calls["n"] >= 2, f"expected gather_logs to retry, got {log_calls['n']} call(s)"

    await _cleanup(state, incident_id)
