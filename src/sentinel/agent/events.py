"""In-process asyncio pub/sub event bus + agent_events persistence (D10).

Every emitted event is persisted to the ``agent_events`` table and published to any subscriber
queue (used later by the SSE stream in Phase 5). The graph nodes emit here so the API layer can
replay/tail the trace without re-walking the graph.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sentinel.db.models import AgentEvent


class Event(BaseModel):
    """A single agent event on the bus."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    node: str
    event_type: str
    payload: dict[str, Any]


class EventBus:
    """A per-incident pub/sub bus that also persists each event to ``agent_events`` (D10)."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Any]] | None = None,
    ) -> None:  # injected for tests / API wiring
        self._session_factory = session_factory
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    def subscribe(self, incident_id: str) -> asyncio.Queue[Event]:
        """Register a subscriber queue for an incident; returns the queue to await on."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[incident_id].add(queue)
        return queue

    def unsubscribe(self, incident_id: str, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.get(incident_id, set()).discard(queue)

    async def emit(
        self, incident_id: str, node: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Persist the event and publish it to subscribers of this incident."""
        self._persist(incident_id, node, event_type, payload)
        event = Event(incident_id=incident_id, node=node, event_type=event_type, payload=payload)
        for queue in list(self._subscribers.get(incident_id, ())):
            queue.put_nowait(event)

    def _persist(
        self, incident_id: str, node: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        if self._session_factory is None:
            return
        try:
            with self._session_factory() as session:
                session.add(
                    AgentEvent(
                        incident_id=UUID(incident_id),
                        node=node,
                        event_type=event_type,
                        payload=payload,
                    )
                )
                session.commit()
        except Exception:  # noqa: BLE001 - event persistence must never break the investigation
            # A missing incident or a transient DB error should not abort the graph run.
            pass
