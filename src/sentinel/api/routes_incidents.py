"""Incident read + approval endpoints (PLAN.md Tasks 5.2/5.3)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from sentinel.api.deps import AppState
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
    channel_values = (cp.checkpoint or {}).get("channel_values", {})
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
