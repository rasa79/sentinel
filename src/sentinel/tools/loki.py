"""Loki client interface (returned by nodes; implemented in Phase 4)."""

from __future__ import annotations

from datetime import timedelta

from sentinel.agent.schemas import LogExcerpt


def query_logs(service: str, since: timedelta, limit: int = 100) -> list[LogExcerpt]:
    """Query Loki for recent log lines for ``service`` (implemented in Phase 4)."""
    raise NotImplementedError("Loki query_logs is implemented in Phase 4")
