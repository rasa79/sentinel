"""Tests for the remediate node's whitelist + confidence enforcement (PLAN.md Task 3.3)."""

from __future__ import annotations

import os

from helpers import load_response, make_config

from sentinel.agent.nodes.remediate import remediate
from sentinel.agent.schemas import DeployEvent, RootCauseHypothesis
from sentinel.config import RemediationSettings, Settings


def _settings(allowed=None, threshold=0.7) -> Settings:
    return Settings(
        _env_file=os.devnull,
        remediation=RemediationSettings(
            allowed_actions=allowed
            or ["restart_service", "rollback_deploy", "scale_replicas", "no_action"],
            confidence_threshold=threshold,
        ),
    )


def _hypothesis(confidence: float = 0.9) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        cause="faulty release", confidence=confidence, evidence=[], affected_service="orders"
    )


def test_remediate_accepts_whitelisted_action(alert) -> None:
    config = make_config(load_response("remediation_ok.json"), settings=_settings())
    state = {"incident_id": "i1", "alert": alert, "hypothesis": _hypothesis(0.9)}
    update = remediate(state, config)
    assert update["remediation"].action == "restart_service"
    assert update.get("escalate") in (None, False)


def test_remediate_forces_no_action_when_confidence_low(alert) -> None:
    config = make_config(load_response("remediation_ok.json"), settings=_settings(threshold=0.95))
    state = {"incident_id": "i1", "alert": alert, "hypothesis": _hypothesis(0.9)}
    update = remediate(state, config)
    assert update["remediation"].action == "no_action"
    assert update["escalate"] is True


def test_remediate_forces_no_action_when_not_whitelisted(alert) -> None:
    # The fake LLM proposes "restart_service", but the whitelist is deliberately restrictive.
    config = make_config(
        load_response("remediation_ok.json"), settings=_settings(allowed=["rollback_deploy"])
    )
    state = {"incident_id": "i1", "alert": alert, "hypothesis": _hypothesis(0.9)}
    update = remediate(state, config)
    assert update["remediation"].action == "no_action"
    assert update["escalate"] is True


def test_remediate_escalates_when_no_hypothesis(alert) -> None:
    config = make_config(load_response("remediation_ok.json"), settings=_settings())
    state = {"incident_id": "i1", "alert": alert}
    update = remediate(state, config)
    assert update["remediation"].action == "no_action"
    assert update["escalate"] is True


_ROLLBACK_RESPONSE = (
    '{"action": "rollback_deploy", "target_service": "orders", "params": {}, '
    '"rationale": "roll back to a good version"}'
)


def test_remediate_injects_previous_version_for_rollback(alert) -> None:
    """A rollback gets its target version from the deploy history (so the executor can act)."""
    config = make_config(_ROLLBACK_RESPONSE, settings=_settings())
    state = {
        "incident_id": "i1",
        "alert": alert,
        "hypothesis": _hypothesis(0.9),
        "deploys": [
            DeployEvent(service="orders", version="1.0.1", event="bad_deploy"),
            DeployEvent(service="orders", version="1.0.0", event="deploy"),
        ],
    }
    update = remediate(state, config)
    assert update["remediation"].action == "rollback_deploy"
    assert update["remediation"].params["previous_version"] == "1.0.0"
    assert update.get("escalate") in (None, False)


def test_remediate_rejects_rollback_with_no_previous_version(alert) -> None:
    """An impossible rollback (no good version in history) becomes no_action/escalate."""
    config = make_config(_ROLLBACK_RESPONSE, settings=_settings())
    state = {
        "incident_id": "i1",
        "alert": alert,
        "hypothesis": _hypothesis(0.9),
        "deploys": [DeployEvent(service="orders", version="1.0.1", event="bad_deploy")],
    }
    update = remediate(state, config)
    assert update["remediation"].action == "no_action"
    assert update["escalate"] is True
