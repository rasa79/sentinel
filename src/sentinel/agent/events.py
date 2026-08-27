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

    # The persisted ``agent_events.id`` (set after the DB write). None when persistence is
    # disabled (no session_factory) or failed; used by the SSE tail to dedupe vs the replay.
    id: str | None = None
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
        # The event loop that owns the subscriber queues, captured at first subscribe. The graph
        # runs on a worker thread (see _stream_and_emit), so emit() must hop across threads.
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, incident_id: str) -> asyncio.Queue[Event]:
        """Register a subscriber queue for an incident; returns the queue to await on."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[incident_id].add(queue)
        # Record the owning loop so emit() can cross the worker-thread boundary correctly.
        self._loop = asyncio.get_running_loop()
        return queue

    def unsubscribe(self, incident_id: str, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.get(incident_id, set()).discard(queue)

    def emit(self, incident_id: str, node: str, event_type: str, payload: dict[str, Any]) -> None:
        """Persist the event and publish it to subscribers of this incident (D10).

        Synchronous by design: the graph runner executes on a worker thread and must not await.
        The publish is non-blocking, and when the graph thread differs from the loop that owns the
        subscriber queues, it hops over via ``call_soon_threadsafe`` so it never touches the
        asyncio.Queue from the wrong thread (which would raise RuntimeError). The SSE generator
        (which awaits ``queue.get``) receives it on the loop thread.
        """
        event_id = self._persist(incident_id, node, event_type, payload)
        event = Event(
            id=event_id, incident_id=incident_id, node=node, event_type=event_type, payload=payload
        )
        loop = self._loop
        for queue in list(self._subscribers.get(incident_id, ())):
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(queue.put_nowait, event)
            else:
                queue.put_nowait(event)

    def _persist(
        self, incident_id: str, node: str, event_type: str, payload: dict[str, Any]
    ) -> str | None:
        """Persist the event; return the DB-generated ``agent_events.id`` (string) or None."""
        if self._session_factory is None:
            return None
        try:
            with self._session_factory() as session:
                record = AgentEvent(
                    incident_id=UUID(incident_id),
                    node=node,
                    event_type=event_type,
                    payload=payload,
                )
                session.add(record)
                session.commit()
                return str(record.id)
        except Exception:  # noqa: BLE001 - event persistence must never break the investigation
            # A missing incident or a transient DB error should not abort the graph run.
            return None
