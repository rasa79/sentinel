"""Tests for the gather nodes (logs/metrics/deploys) that call tool interfaces."""

from helpers import make_config

from sentinel.agent.nodes.gather_deploys import gather_deploys
from sentinel.agent.nodes.gather_logs import gather_logs
from sentinel.agent.nodes.gather_metrics import gather_metrics
from sentinel.agent.schemas import DeployEvent, LogExcerpt, MetricFinding


async def test_gather_logs_happy_path(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_logs.query_logs",
        lambda service, since, limit=100: [
            LogExcerpt(service=service, message="boom", level="error")
        ],
    )
    update = await gather_logs({"incident_id": "i1", "alert": alert}, make_config())
    assert len(update["logs"]) == 1
    assert update["logs"][0].message == "boom"


async def test_gather_logs_empty_result(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_logs.query_logs", lambda service, since, limit=100: []
    )
    update = await gather_logs({"incident_id": "i1", "alert": alert}, make_config())
    assert update["logs"] == []


async def test_gather_metrics_happy_path(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_metrics.query_anomalies",
        lambda service, window: [MetricFinding(metric="http_errors_total", value=3.0, breach=True)],
    )
    update = await gather_metrics({"incident_id": "i1", "alert": alert}, make_config())
    assert update["metrics"][0].breach is True


async def test_gather_metrics_empty_result(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_metrics.query_anomalies", lambda service, window: []
    )
    update = await gather_metrics({"incident_id": "i1", "alert": alert}, make_config())
    assert update["metrics"] == []


async def test_gather_deploys_happy_path(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_deploys.query_deploys",
        lambda service, limit=20: [
            DeployEvent(service="orders", version="1.0.1", event="bad_deploy")
        ],
    )
    update = await gather_deploys({"incident_id": "i1", "alert": alert}, make_config())
    assert update["deploys"][0].event == "bad_deploy"


async def test_gather_deploys_empty_result(alert, monkeypatch) -> None:
    monkeypatch.setattr(
        "sentinel.agent.nodes.gather_deploys.query_deploys", lambda service, limit=20: []
    )
    update = await gather_deploys({"incident_id": "i1", "alert": alert}, make_config())
    assert update["deploys"] == []
