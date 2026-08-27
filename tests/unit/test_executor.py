"""Unit tests for the Docker remediation executor (D11) with a mocked docker client."""

from __future__ import annotations

import os

import pytest

from sentinel.config import RemediationSettings, Settings
from sentinel.tools.executor import RemediationNotAllowed, execute


class _FakeContainer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.restarted = 0

    def restart(self) -> None:
        self.restarted += 1


class _FakeContainers:
    def __init__(self, containers: list[_FakeContainer]) -> None:
        self._containers = containers

    def list(
        self, filters: dict[str, str] | None = None, all: bool = False
    ) -> list[_FakeContainer]:  # noqa: A002
        name = (filters or {}).get("name", "")
        return [c for c in self._containers if name in c.name]


class _FakeClient:
    def __init__(self, containers: list[_FakeContainer]) -> None:
        self.containers = _FakeContainers(containers)


def _settings(
    allowed_actions: list[str] | None = None, allowed_services: list[str] | None = None
) -> Settings:
    return Settings(
        _env_file=os.devnull,
        remediation=RemediationSettings(
            allowed_actions=allowed_actions
            or ["restart_service", "rollback_deploy", "scale_replicas", "no_action"],
            allowed_services=allowed_services or ["orders", "payments", "inventory"],
        ),
    )


def test_non_whitelisted_action_raises_before_any_docker_call() -> None:
    client = _FakeClient([])
    with pytest.raises(RemediationNotAllowed):
        execute(
            "drop_db",
            "orders",
            settings=_settings(allowed_actions=["restart_service"]),
            client=client,
        )
    assert client.containers._containers == []  # no docker interaction happened


def test_non_whitelisted_service_raises() -> None:
    with pytest.raises(RemediationNotAllowed):
        execute(
            "restart_service",
            "payments",
            settings=_settings(allowed_services=["orders"]),
            client=_FakeClient([]),
        )


def test_dry_run_makes_zero_mutation_calls() -> None:
    container = _FakeContainer("deploy-orders-1")
    result = execute(
        "restart_service",
        "orders",
        dry_run=True,
        settings=_settings(),
        client=_FakeClient([container]),
    )
    assert result.dry_run is True
    assert result.status == "dry_run"
    assert container.restarted == 0


def test_restart_service_for_real_calls_restart() -> None:
    container = _FakeContainer("deploy-orders-1")
    result = execute(
        "restart_service",
        "orders",
        dry_run=False,
        settings=_settings(),
        client=_FakeClient([container]),
    )
    assert container.restarted == 1
    assert result.status == "ok"


def test_rollback_with_no_previous_version_escalates() -> None:
    result = execute(
        "rollback_deploy",
        "orders",
        dry_run=False,
        settings=_settings(),
        client=_FakeClient([_FakeContainer("deploy-orders-1")]),
    )
    assert result.status == "escalated"


def test_scale_replicas_returns_not_applicable_on_single_replica() -> None:
    result = execute(
        "scale_replicas",
        "orders",
        dry_run=False,
        settings=_settings(),
        client=_FakeClient([_FakeContainer("deploy-orders-1")]),
    )
    assert result.status == "not_applicable"


def test_no_action_is_a_noop() -> None:
    result = execute(
        "no_action", "orders", dry_run=False, settings=_settings(), client=_FakeClient([])
    )
    assert result.status == "noop"
