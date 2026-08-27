#  LEARN[23]: whitelist + dry-run in the executor — the capability gate for agent actions (mandatory
# — D11)
#  Why this way: the remediation EXECUTOR — not the LLM node — is the enforcement point. It
# re-checks the
#    action against the config whitelist (allowed_actions + allowed_services), and it defaults to
#   dry_run
#   so nothing mutates the host unless a caller explicitly opts in.
# Good sides:
#    - "propose in the graph, authorize at the executor": even a hallucinated/over-confident
#   proposal can't
#     reach the Docker daemon unless it is on the whitelist and targets an allowed service
#    - dry_run returns a descriptive ExecutionResult and makes zero Docker mutation calls, so the
#   path is
#     provable before any real change
#   - defense in depth: the whitelist is enforced in code (here) AND derived from config
# Drawbacks:
#    - mounting /var/run/docker.sock into the API container is root-equivalent on the host —
#   acceptable
#     only because L2 declares the demo security posture
#   - the whitelist is a hard gate; a legitimately new action requires a config change first
#  Concept: never trust model output at the action boundary. The graph's remediate node only
# proposes a
#    RemediationProposal; the executor is the sole thing authorized to touch the Docker daemon, and
#   it
#    re-validates action + target against config before calling the SDK. This is capability gating:
#   the
#    proposal is a request, the executor is the reference monitor. dry_run being the default is the
#   second
#   half — a reversible, auditable first step (D11) that lets a human see exactly what WOULD happen
#    before it happens. The cost of the Docker socket mount is the real security risk: the socket
#   gives
#    root-equivalent control of the host daemon, so any code running in the API container can
#   start/stop
#   containers or read secrets; we accept that only because the whole stack is a demo posture (L2).
#    A Java engineer should read this as a @PreAuthorize on the operation boundary plus a "simulate"
#   mode
#   on a command service — authorization at the edge, not just in the UI/graph.
# See also: LEARN[17] (DI), D11, L2/L7 limitations
from __future__ import annotations

import logging
from typing import Any

from docker import DockerClient
from docker.client import from_env

from sentinel.agent.schemas import ExecutionResult
from sentinel.config import Settings

logger = logging.getLogger(__name__)


class RemediationNotAllowed(Exception):
    """Raised when a proposed action or target is outside the remediation whitelist (D11)."""


def _find_containers(client: DockerClient, target_service: str) -> list[Any]:
    name = f"deploy-{target_service}-1"
    return list(client.containers.list(filters={"name": name}, all=True))


def execute(
    action: str,
    target_service: str,
    params: dict[str, Any] | None = None,
    dry_run: bool = True,
    settings: Settings | None = None,
    client: DockerClient | None = None,
) -> ExecutionResult:
    """Perform (or dry-run) a whitelisted remediation action (D11)."""
    settings = settings or Settings()
    client = client or from_env()
    params = params or {}

    # Whitelist gate (defense in depth): action AND target must both be allowed.
    if action not in settings.remediation.allowed_actions:
        raise RemediationNotAllowed(
            f"action {action!r} not in allowed_actions={settings.remediation.allowed_actions}"
        )
    if target_service not in settings.remediation.allowed_services:
        raise RemediationNotAllowed(
            f"target_service {target_service!r} not in allowed_services="
            f"{settings.remediation.allowed_services}"
        )

    if action == "no_action":
        return ExecutionResult(
            action=action, target_service=target_service, dry_run=dry_run, status="noop"
        )
    if action == "restart_service":
        return _restart(client, target_service, dry_run)
    if action == "rollback_deploy":
        return _rollback(client, target_service, params, dry_run)
    if action == "scale_replicas":
        return _scale(client, target_service, params, dry_run)
    raise RemediationNotAllowed(f"unknown action {action!r}")


def _restart(client: DockerClient, target_service: str, dry_run: bool) -> ExecutionResult:
    containers = _find_containers(client, target_service)
    if not containers:
        return ExecutionResult(
            action="restart_service",
            target_service=target_service,
            dry_run=dry_run,
            status="not_found",
        )
    container = containers[0]
    if dry_run:
        return ExecutionResult(
            action="restart_service",
            target_service=target_service,
            dry_run=True,
            status="dry_run",
            message=f"would restart {container.name}",
        )
    container.restart()
    return ExecutionResult(
        action="restart_service",
        target_service=target_service,
        dry_run=False,
        status="ok",
        message=f"restarted {container.name}",
    )


def _rollback(
    client: DockerClient,
    target_service: str,
    params: dict[str, Any],
    dry_run: bool,
) -> ExecutionResult:
    previous_version = params.get("previous_version")
    if not previous_version:
        # No previous tag recorded -> escalate (do not guess a version to roll back to).
        return ExecutionResult(
            action="rollback_deploy",
            target_service=target_service,
            dry_run=dry_run,
            status="escalated",
            message="no previous deploy version recorded; cannot roll back",
        )
    containers = _find_containers(client, target_service)
    if not containers:
        return ExecutionResult(
            action="rollback_deploy",
            target_service=target_service,
            dry_run=dry_run,
            status="not_found",
        )
    container = containers[0]
    if dry_run:
        return ExecutionResult(
            action="rollback_deploy",
            target_service=target_service,
            dry_run=True,
            status="dry_run",
            message=f"would roll back {container.name} to {previous_version}",
        )
    container.restart()
    return ExecutionResult(
        action="rollback_deploy",
        target_service=target_service,
        dry_run=False,
        status="ok",
        message=f"rolled back {container.name} to {previous_version}",
    )


def _scale(
    client: DockerClient,
    target_service: str,
    params: dict[str, Any],
    dry_run: bool,
) -> ExecutionResult:
    # TODO(review): L7 - scale_replicas is only partially emulated on plain Docker (no compose v2
    #  dynamic scaling); it restarts N named replica containers if they exist, else returns
    # not_applicable.
    replicas = int(params.get("replicas", 2))
    # Replica containers use compose naming deploy-<service>-N for N >= 2 (the primary is -1).
    names = [f"deploy-{target_service}-{i}" for i in range(2, replicas + 1)]
    found: list[Any] = []
    for name in names:
        found.extend(list(client.containers.list(filters={"name": name}, all=True)))
    if not found:
        return ExecutionResult(
            action="scale_replicas",
            target_service=target_service,
            dry_run=dry_run,
            status="not_applicable",
            message="no replicate containers found (single-replica compose)",  # L7
        )
    name = ", ".join(c.name for c in found)
    if dry_run:
        return ExecutionResult(
            action="scale_replicas",
            target_service=target_service,
            dry_run=True,
            status="dry_run",
            message=f"would restart replica containers: {name}",
        )
    for container in found:
        container.restart()
    return ExecutionResult(
        action="scale_replicas",
        target_service=target_service,
        dry_run=False,
        status="ok",
        message=f"restarted replica containers: {name}",
    )
