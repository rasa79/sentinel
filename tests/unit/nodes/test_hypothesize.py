"""Tests for the hypothesize node (PLAN.md Task 3.3)."""

from helpers import load_response, make_config

from sentinel.agent.nodes.hypothesize import hypothesize
from sentinel.agent.schemas import RootCauseHypothesis


def test_hypothesize_parses_fake_llm(alert) -> None:
    config = make_config(load_response("hypothesis_ok.json"))
    state = {
        "incident_id": "i1",
        "alert": alert,
        "logs": [],
        "metrics": [],
        "deploys": [],
        "runbooks": [],
    }
    update = hypothesize(state, config)
    assert isinstance(update["hypothesis"], RootCauseHypothesis)
    assert update["hypothesis"].affected_service == "orders"


def test_hypothesize_with_empty_evidence(alert) -> None:
    config = make_config(load_response("hypothesis_ok.json"))
    state = {"incident_id": "i1", "alert": alert}
    update = hypothesize(state, config)
    assert update["hypothesis"].cause.startswith("A faulty release")
