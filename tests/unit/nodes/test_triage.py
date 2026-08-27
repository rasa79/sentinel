"""Tests for the triage node (PLAN.md Task 3.3)."""

import pytest
from helpers import load_response, make_config

from sentinel.agent.nodes.triage import triage
from sentinel.agent.schemas import TriageResult


def test_triage_parses_fake_llm(alert) -> None:
    config = make_config(load_response("triage_ok.json"))
    update = triage({"incident_id": "i1", "alert": alert}, config)
    assert isinstance(update["triage"], TriageResult)
    assert update["triage"].category == "latency_spike"
    assert update["triage"].affected_service == "orders"


def test_triage_requires_llm_in_config(alert) -> None:
    with pytest.raises(KeyError):
        triage({"incident_id": "i1", "alert": alert}, make_config())
