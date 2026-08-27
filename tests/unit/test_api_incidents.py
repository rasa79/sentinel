"""Unit tests for the incident read APIs (Task 5.2) with a faked DB session."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import httpx

from sentinel.api.app import create_app
from sentinel.api.deps import AppState
from sentinel.config import Settings
from sentinel.db.models import AgentEvent, Incident


class _FakeIncident:
    def __init__(
        self, incident_id: uuid.UUID, name: str, service: str, status: str = "investigating"
    ):
        self.id = incident_id
        self.alert_name = name
        self.service = service
        self.severity = "high"
        self.status = status
        self.created_at = datetime.now(UTC)


class _FakeEvent:
    def __init__(self, node: str, event_type: str, payload: dict):
        self.id = 1
        self.node = node
        self.event_type = event_type
        self.payload = payload
        self.created_at = datetime.now(UTC)


class _FakeQuery:
    def __init__(self, items: list) -> None:
        self._items = list(items)

    def filter(self, *args: object) -> _FakeQuery:
        return self

    def order_by(self, *args: object) -> _FakeQuery:
        return self

    def limit(self, n: int) -> _FakeQuery:
        self._items = self._items[:n]
        return self

    def offset(self, n: int) -> _FakeQuery:
        self._items = self._items[n:]
        return self

    def count(self) -> int:
        return len(self._items)

    def all(self) -> list:
        return self._items


class _FakeSession:
    def __init__(self, incidents: list[_FakeIncident], events: list[_FakeEvent]) -> None:
        self._incidents = incidents
        self._events = events

    def query(self, model: object) -> _FakeQuery:
        if model is Incident:
            return _FakeQuery(self._incidents)
        if model is AgentEvent:
            return _FakeQuery(self._events)
        raise AssertionError(f"unexpected model {model}")

    def get(self, model: object, incident_id: object) -> _FakeIncident | None:
        if model is not Incident:
            return None
        for incident in self._incidents:
            if incident.id == incident_id:
                return incident
        return None

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


def _make_app(incidents: list[_FakeIncident], events: list[_FakeEvent]):
    state = AppState(
        settings=Settings(_env_file=os.devnull),
        session_factory=_FakeFactory(_FakeSession(incidents, events)),
        graph=None,
        event_bus=None,  # type: ignore[arg-type]
        llm=None,  # type: ignore[arg-type]
        checkpointer=None,
    )
    return create_app(state)


async def test_list_incidents_returns_items() -> None:
    inc = _FakeIncident(uuid.uuid4(), "HighErrorRate", "orders", "investigating")
    app = _make_app([inc], [])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get("/incidents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["alert_name"] == "HighErrorRate"


async def test_get_incident_returns_ordered_trace() -> None:
    incident_id = uuid.uuid4()
    inc = _FakeIncident(incident_id, "HighErrorRate", "orders")
    events = [
        _FakeEvent("triage", "started", {"step": 1}),
        _FakeEvent("hypothesize", "started", {"step": 2}),
    ]
    app = _make_app([inc], events)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get(f"/incidents/{incident_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident"]["id"] == str(incident_id)
    assert [e["node"] for e in body["events"]] == ["triage", "hypothesize"]


async def test_get_incident_unknown_id_returns_404() -> None:
    app = _make_app([], [])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        resp = await client.get(f"/incidents/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "incident not found"
