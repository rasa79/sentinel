"""SSE streaming endpoint for an incident's live trace (PLAN.md Task 5.4 / D10).

The stream replays persisted ``agent_events`` and then tails the in-process event bus until the
incident reaches a terminal status. See LEARN[27] for the SSE-vs-WebSocket decision, the
replay-then-live consistency problem, and the id-based dedupe that closes the gap.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from sentinel.api.deps import AppState
from sentinel.db.models import AgentEvent, Incident

router = APIRouter()

# An incident in one of these states has no more graph work to run; the stream can end.
_TERMINAL_STATUSES = frozenset({"resolved", "rejected", "escalated"})
_IDLE_POLL_SECONDS = 1.0
_HEARTBEAT_SECONDS = 15.0


#  LEARN[27]: SSE vs WebSocket, and the replay-then-live dedupe (mandatory placement, deep-dive —
# D10)
#  Why this way: the CLI/watch and the browser get a one-way, server->client push of the agent's
# node-by-node trace. A single HTTP response with ``text/event-stream`` is enough: the client never
#   sends anything back on this connection (approvals go over POST /incidents/{id}/approve), so a
#   full-duplex WebSocket buys nothing here. Using one-way SSE keeps the whole feature on plain HTTP
#   (no upgrade handshake, no connection-lifecycle state to manage, trivially proxied by nginx/any
#    HTTP load balancer, backpressure is just HTTP flow control — a slow client stalls the TCP
#    window rather than forcing us to buffer). For the Spring reader this is exactly Spring MVC's
#   ``SseEmitter`` / Spring WebFlux ``Flux<ServerSentEvent>``: one long-lived response the server
#   writes to as things happen.
# Good sides:
#   - the event source is a plain iterable of SSE frames (``EventSourceResponse``), so the whole
#     stream is one async generator — easy to test and to reason about (see _incident_stream)
#   - replay-then-live means a client connecting mid-run does NOT miss earlier nodes; the trace is
#     ordered and complete
#   - the bus already persists every event to ``agent_events`` (D10), so replay uses the durable
#     source of truth and live tail uses the in-memory queue: one event model, two read paths
#   - heartbeat keeps intermediary proxies and the browser from timing the idle connection out
# Drawbacks:
#   - SSE is one-way only, so if we ever want the browser to request mid-stream actions on the same
#     connection we would need WebSocket (we do not: approvals are separate POSTs)
#   - the in-memory asyncio.Queue is process-local: if the API process restarts, the live tail drops
#     (replay still works from agent_events); for a single-process demo this is fine (L3), and it is
#     the same limitation LEARN[24] accepts for the background investigation task
#   - a client that never disconnects and never reaches terminal leaves the generator suspended on
#     ``queue.get``; we rely on the client closing the connection (FastAPI cancels the task) rather
#     than a server-side timeout
# Concept: think of an incident's trace as a log that is appended to concurrently. A reader has two
# ways to observe it: read what is already there (replay from agent_events) or subscribe to new
# lines (the bus). If you do "read, then subscribe", a line written between those two steps is lost
# — the exact gap that a naive implementation hits. The fix inverts the order and dedupes: subscribe
#   to the live queue FIRST (so no future line is missed), then read history, then drain the queue
#   skipping any line whose persisted ``agent_events.id`` already appeared in history. The id is the
#   key insight: because the bus persists the event (and thus assigns it a DB id) BEFORE publishing
#   it, an event written in the overlap window is present in BOTH the history read and the live
#   queue under the SAME id, so dedupe drops the exact duplicate rather than the real event. Change
#   assumption (e.g. publish before persist, or use a non-stable key) and you either lose events in
#   the gap or emit duplicates — the bug is not visible in the generator alone, which is the restate
#   test (QS-3). SSE frames are lines of ``key: value``; browsers and curl -N both read them, and
#   comments (``: text``) are ignored by clients, which is what makes the heartbeat harmless.
# See also: LEARN[24] (background asyncio task vs a task queue), LEARN[26] (the approval resume the
# stream tail watches), LEARN[19] (the checkpointer that makes resume durable)


def _event(
    incident_id: str, event_type: str, node: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build an SSE frame dict: an ``event`` name plus a JSON ``data`` string."""
    data = {"incident_id": incident_id, "node": node, "event_type": event_type, "payload": payload}
    return {
        "event": event_type,
        "data": json.dumps(data, default=str),
    }


def _read_history(state: AppState, incident_id: str) -> list[dict[str, Any]]:
    """Return the persisted trace for an incident, oldest first."""
    with state.session_factory() as session:
        events = (
            session.query(AgentEvent)
            .filter(AgentEvent.incident_id == UUID(incident_id))
            .order_by(AgentEvent.created_at.asc(), AgentEvent.id.asc())
            .all()
        )
    return [
        {
            "id": str(e.id),
            "node": e.node,
            "event_type": e.event_type,
            "payload": e.payload,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


def _current_status(state: AppState, incident_id: str) -> str | None:
    with state.session_factory() as session:
        incident = session.get(Incident, UUID(incident_id))
        return incident.status if incident else None


async def _incident_stream(state: AppState, incident_id: str) -> Any:
    """Replay history then tail live bus events until the incident reaches a terminal status.

    Ordering rule (LEARN[27]): never close while there are still queued events to deliver. A run
    that finishes emits all of its events into the queue (via ``call_soon_threadsafe``) before its
    status flips to terminal, so on the empty-idle poll we are safe to close. This guarantees the
    final verify/report events are not dropped by an eager terminal check.
    """
    queue = state.event_bus.subscribe(incident_id)
    try:
        # 1. Subscribe first, then replay: events emitted in the overlap window are in both the
        #    history read and the queue, so we dedupe by the persisted id (LEARN[27]).
        history = _read_history(state, incident_id)
        seen: set[str] = set()
        for ev in history:
            seen.add(ev["id"])
            yield _event(incident_id, "history", ev["node"], ev)

        # 2. Tail live events. awaiting_approval is NOT terminal: the stream must stay open so the
        #    CLI can approve and the resulting run is streamed live.
        last_heartbeat = time.monotonic()
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_IDLE_POLL_SECONDS)
            except TimeoutError:
                # Idle. If the run is already terminal (and the queue is drained above), close;
                # otherwise keep it alive, sending a heartbeat on the 15s cadence.
                status = _current_status(state, incident_id)
                if status in _TERMINAL_STATUSES:
                    yield _event(incident_id, "run_complete", None, {"status": status})
                    return
                now = time.monotonic()
                if now - last_heartbeat >= _HEARTBEAT_SECONDS:
                    yield {"comment": "heartbeat"}
                    last_heartbeat = now
                continue
            if event.id is not None and event.id in seen:
                continue  # already replayed (overlap window) — the dedupe (LEARN[27])
            if event.id is not None:
                seen.add(event.id)
            yield _event(incident_id, event.event_type, event.node, event.payload)
    finally:
        state.event_bus.unsubscribe(incident_id, queue)


@router.get("/incidents/{incident_id}/stream")
async def stream_incident(incident_id: UUID, request: Request) -> EventSourceResponse:
    """SSE stream of an incident's agent trace (replay then live), closing on terminal status."""
    state: AppState = request.app.state.sentinel
    with state.session_factory() as session:
        if session.get(Incident, incident_id) is None:
            raise HTTPException(status_code=404, detail="incident not found")
    return EventSourceResponse(_incident_stream(state, str(incident_id)))
