"""Docker remediation executor interface (whitelist + dry-run; implemented in Phase 4)."""

from __future__ import annotations

from typing import Any

from sentinel.agent.schemas import ExecutionResult


def execute(
    action: str,
    target_service: str,
    params: dict[str, Any],
    dry_run: bool = True,
) -> ExecutionResult:
    """Perform (or dry-run) a whitelisted remediation action (implemented in Phase 4)."""
    raise NotImplementedError("executor execute is implemented in Phase 4")
