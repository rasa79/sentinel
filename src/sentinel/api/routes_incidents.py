"""Incident read + approval endpoints (PLAN.md Tasks 5.2/5.3).

The approval endpoints resume the graph through the checkpointer (D6). See LEARN[26] for the
API-side reasoning; the deep-dive on interrupt vs polling is in LEARN[20].
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from sentinel.api.deps import AppState, resume_investigation
from sentinel.db.models import AgentEvent, Incident

router = APIRouter()


class IncidentSummary(BaseModel):
    id: str
    alert_name: str
    service: str
    severity: str
    status: str
    created_at: str | None = None


def _incident_summary(incident: Incident) -> dict[str, Any]:
    return {
        "id": str(incident.id),
        "alert_name": incident.alert_name,
        "service": incident.service,
        "severity": incident.severity,
        "status": incident.status,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
    }


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def _state_summary(state: AppState, incident_id: str) -> dict[str, Any]:
    """Return the latest graph checkpoint's agent-relevant state as a JSON-able summary."""
    if state.checkpointer is None:
        return {}
    cp = state.checkpointer.get({"configurable": {"thread_id": incident_id}})
    if cp is None:
        return {}
    channel_values = cp.get("channel_values", {})
    keys = [
        "triage",
        "hypothesis",
        "remediation",
        "execution",
        "verification",
        "report",
        "approval",
        "escalate",
    ]
    summary = {k: _serialize(channel_values.get(k)) for k in keys if k in channel_values}
    report = channel_values.get("report")
    if report is not None:
        summary["status"] = getattr(report, "status", None) or (
            report.get("status") if isinstance(report, dict) else None
        )
    return summary


@router.get("/incidents")
async def list_incidents(
    request: Request, status: str | None = None, page: int = 1, per_page: int = 20
) -> dict[str, Any]:
    """List incidents, optionally filtered by status, with simple pagination."""
    state: AppState = request.app.state.sentinel
    with state.session_factory() as session:
        query = session.query(Incident).order_by(Incident.created_at.desc())
        if status:
            query = query.filter(Incident.status == status)
        total = query.count()
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [_incident_summary(i) for i in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: UUID, request: Request) -> dict[str, Any]:
    """Return an incident plus its ordered agent_events trace and a graph state summary."""
    state: AppState = request.app.state.sentinel
    with state.session_factory() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        events = (
            session.query(AgentEvent)
            .filter(AgentEvent.incident_id == incident_id)
            .order_by(AgentEvent.created_at.asc())
            .all()
        )
        event_trace = [
            {
                "id": e.id,
                "node": e.node,
                "event_type": e.event_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    return {
        "incident": _incident_summary(incident),
        "events": event_trace,
        "state": _state_summary(state, str(incident_id)),
    }


#  LEARN[26]: resume through the checkpointer, the 409 guard, and concurrent approvals (QS-4
# cross-ref)
#  Why this way: approve/reject resume the graph with Command(resume=...) into the checkpointer,
# guard
#   with a 409 when the incident is not awaiting_approval, and run the resume on a background task.
#   This is a cross-reference stub: the interrupt-vs-polling deep-dive is in LEARN[20].
# Good sides:
#   - resume goes through the same checkpoint the graph yielded at, so an in-memory graph handle is
#     never needed (a process restart is transparent); D6
#    - the 409 guard maps to the "pending interrupt" state, so approving a non-pending incident is
#   409
# Drawbacks:
#    - a concurrent approve/reject races: the checkpointer is a single writer, so the last resume
#   wins
#   - the 409 check is a read-then-act, not atomic, so two rapid approvals can both pass the guard
#  Concept: LangGraph persists the interrupt in the checkpoint (LEARN[19]); resume() replays from
# there
#   by re-entering the graph with the same thread_id and Command(resume=...). The API never holds a
#    graph object; it only knows the incident id and re-invokes the graph over the checkpointer,
#   which is
#    exactly what lets a restarted API process resume a pending approval (no orphaned in-memory
#   state).
#   The 409 maps to the interrupt state: an incident that is NOT awaiting_approval has no pending
#    interrupt, so a resume would be meaningless (or would replay the wrong state). Two approvals
#   racing:
#    both may pass the guard's read, but the checkpointer serializes them as single-writer, so the
#   last
#    one wins — the classic "optimistic but not atomic" trade-off, acceptable because a human
#   decision is
#   rare and the checkpointer gives last-writer semantics.
# See also: LEARN[20] (interrupt vs polling), LEARN[19] (checkpointer), the D6 section in PLAN.md
def _resume(request: Request, incident_id: UUID, approved: bool) -> dict[str, str]:
    state: AppState = request.app.state.sentinel
    with state.session_factory() as session:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")
        if incident.status != "awaiting_approval":
            raise HTTPException(status_code=409, detail="incident is not awaiting approval")
    asyncio.create_task(resume_investigation(state, str(incident_id), approved))
    return {"incident_id": str(incident_id), "status": "approving" if approved else "rejecting"}


@router.post("/incidents/{incident_id}/approve", status_code=202)
async def approve_incident(incident_id: UUID, request: Request) -> dict[str, str]:
    """Resume the interrupted graph with an approval."""
    return _resume(request, incident_id, approved=True)


@router.post("/incidents/{incident_id}/reject", status_code=202)
async def reject_incident(incident_id: UUID, request: Request) -> dict[str, str]:
    """Resume the interrupted graph with a rejection (routes to report as rejected)."""
    return _resume(request, incident_id, approved=False)
