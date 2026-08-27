"""Tests for the verify node (D15) — resolved vs breaching."""

from helpers import make_config

from sentinel.agent.nodes.verify import verify
from sentinel.agent.schemas import MetricFinding


def test_verify_resolved_when_no_breach(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.verify.instant_query",
        lambda expr: [MetricFinding(metric="x", value=0.0, breach=False)],
    )
    update = verify({"incident_id": "i1", "alert": alert}, make_config())
    assert update["verification"].resolved is True


def test_verify_not_resolved_when_breaching(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.verify.instant_query",
        lambda expr: [MetricFinding(metric="x", value=5.0, breach=True)],
    )
    update = verify({"incident_id": "i1", "alert": alert}, make_config())
    assert update["verification"].resolved is False
    assert update["verification"].values == [5.0]
