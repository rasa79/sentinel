"""Deploy-event query interface (reads the shared deployments table; implemented in Phase 4)."""

from __future__ import annotations

from sentinel.agent.schemas import DeployEvent


def query_deploys(service: str, limit: int = 20) -> list[DeployEvent]:
    """Return recent deploy events for ``service`` (implemented in Phase 4)."""
    raise NotImplementedError("deploys query_deploys is implemented in Phase 4")
