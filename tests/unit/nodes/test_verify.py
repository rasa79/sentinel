"""Tests for the verify node's fixed-window verification loop (D15 / Phase 6).

Metric sequences under test: clear-on-first, clear-on-third, never-clear. ``time.sleep`` and the
Prometheus client are mocked so the loop is deterministic and fast.
"""

from __future__ import annotations

import os
from typing import Any

from helpers import make_config

from sentinel.agent.nodes.verify import verify
from sentinel.agent.schemas import MetricFinding
from sentinel.config import Settings, VerificationSettings

_CLEAR = [MetricFinding(metric="x", value=0.0, breach=False)]
_BREACH = [MetricFinding(metric="x", value=5.0, breach=True)]


def _config() -> dict[str, Any]:
    return make_config(
        settings=Settings(
            _env_file=os.devnull, verification=VerificationSettings(delay_seconds=0, attempts=3)
        )
    )


def _sequence(seq: list[list[MetricFinding]]) -> Any:
    """Return a `(calls, fake)` where fake returns seq[i] on the i-th call (last repeats)."""
    calls = {"n": 0}

    def _fake(expr: str) -> list[MetricFinding]:  # noqa: ARG001
        i = calls["n"]
        calls["n"] += 1
        return seq[min(i, len(seq) - 1)]

    return calls, _fake


def test_verify_clear_on_first(alert, monkeypatch) -> None:
    calls, fake = _sequence([_CLEAR])
    monkeypatch.setattr("sentinel.agent.nodes.verify.instant_query", fake)
    monkeypatch.setattr("sentinel.agent.nodes.verify.time.sleep", lambda s: None)
    update = verify({"incident_id": "i1", "alert": alert}, _config())
    assert update["verification"].resolved is True
    assert update["verification"].attempts == 1
    assert calls["n"] == 1


def test_verify_clear_on_third(alert, monkeypatch) -> None:
    calls, fake = _sequence([_BREACH, _BREACH, _CLEAR])
    monkeypatch.setattr("sentinel.agent.nodes.verify.instant_query", fake)
    monkeypatch.setattr("sentinel.agent.nodes.verify.time.sleep", lambda s: None)
    update = verify({"incident_id": "i1", "alert": alert}, _config())
    assert update["verification"].resolved is True
    assert update["verification"].attempts == 3
    assert calls["n"] == 3
    assert update["verification"].values == [5.0, 5.0, 0.0]


def test_verify_never_clear_is_escalated(alert, monkeypatch) -> None:
    calls, fake = _sequence([_BREACH, _BREACH, _BREACH])
    monkeypatch.setattr("sentinel.agent.nodes.verify.instant_query", fake)
    monkeypatch.setattr("sentinel.agent.nodes.verify.time.sleep", lambda s: None)
    update = verify({"incident_id": "i1", "alert": alert}, _config())
    assert update["verification"].resolved is False
    assert update["verification"].attempts == 3
    assert calls["n"] == 3
    assert update["verification"].values == [5.0, 5.0, 5.0]


def test_verify_emits_escalation_event_when_never_clear(alert, monkeypatch) -> None:
    events: list[tuple[str, str, str, dict[str, Any]]] = []
    bus = type("Bus", (), {"emit": lambda self, *a: events.append(a)})

    calls, fake = _sequence([_BREACH, _BREACH, _BREACH])
    monkeypatch.setattr("sentinel.agent.nodes.verify.instant_query", fake)
    monkeypatch.setattr("sentinel.agent.nodes.verify.time.sleep", lambda s: None)
    config = dict(_config())
    config["configurable"]["event_bus"] = bus()
    config["configurable"]["thread_id"] = "i1"

    update = verify({"incident_id": "i1", "alert": alert}, config)
    assert update["verification"].resolved is False
    assert events, "expected an escalation event"
    # emit(incident_id, node, event_type, payload)
    incident_id, node, event_type, payload = events[0]
    assert incident_id == "i1" and node == "verify" and event_type == "escalation"
    assert payload["values"] == [5.0, 5.0, 5.0]
