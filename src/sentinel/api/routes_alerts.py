# LEARN[24]: a background asyncio task vs a task queue (Celery/Temporal) for the investigation run
#  Why this way: the webhook launches the graph as a background asyncio task
# (``asyncio.create_task``)
#   rather than handing it to a real task queue. This is right for a single-process demo, and it is
#   honest about what it gives up.
# Good sides:
#   - no broker/worker to deploy; the run lives in the same process as the API
#   - the graph is already durable via the checkpointer, so once it reaches the first checkpoint the
#     run survives an app crash (it can be resumed)
# Drawbacks:
#   - a crash BEFORE the first checkpoint loses the run (no queue-level retry after a failure)
#   - no distribution: a second API process cannot pick up the work, and concurrent runs share the
#     single process (ties to L3)
#   - long/blocking runs share the API process's resources
#  Concept: a task queue (Celery/Temporal) decouples "schedule work" from "do work" and gives
# retries,
#    a dead-letter path and horizontal scaling. That buying of durability-before-execution matters
#   when a
#    job can fail and you must not lose it. Here the *graph* is the durable unit: LangGraph's
#   checkpointer
#    writes a checkpoint after each node, so even though the asyncio task is fire-and-forget, once
#   it has
#    reached the human_gate interrupt the run is resumable from the DB (see LEARN[19]). If the
#   process dies
#    before that first checkpoint, the task is lost — the same window a task queue would cover with
#   an
#    acknowledgement + retry. Choosing an asyncio task is a deliberate scope cut for a
#   single-process demo
#   (recorded under L3); a production system would use a queue for at-least-once delivery.
# See also: LEARN[19] (checkpointer durability), L3 limitation, D10
# ---------------------------------------------------------------------------
#  LEARN[25]: the Alertmanager v4 webhook payload and the dedupe choice (for someone new to alert
# grouping)
# Why this way: POST /alerts/webhook accepts an Alertmanager v4 payload, maps the FIRST alert to an
#    Incident, and dedupes by alertname+service within 60s to the existing incident instead of
#   forking a
#   new investigation per notification.
# Good sides:
#   - ingesting a standard alert shape means a real Alertmanager can forward to us unchanged
#   - dedupe-on-ingest keeps one incident per (alertname, service) rather than one per notification
# Drawbacks:
#    - only the first alert is used; a grouped batch's other alerts are ignored (a demo
#   simplification)
#    - the 60s window is a fixed heuristic; an alert that re-fires after a pause creates a new
#   incident
#  Concept: Alertmanager groups related alerts into a single notification with a list of ``alerts``,
# each
#   with ``labels`` (identifying attributes, e.g. alertname, service) and ``annotations`` (human
#    context). The webhook body is that notification; we take ``alerts[0]`` and read its labels. The
#   dedupe
#    is an idempotency guard: same (alertname, service) within 60s returns the existing incident id,
#   so a
#   flapping alert or a redundant notification doesn't spawn parallel investigations into the same
#    symptom. This is the same "idempotency key" idea as a webhook dedupe in an order-processing
#   system —
#   the key is the natural grouping (alertname + service) plus a short time window. In a real system
#   Alertmanager's own grouping + inhibit rules would do more of this work; here we keep it minimal.
# See also: LEARN[24] (background task), the incident model in db/models.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from sentinel.agent.schemas import AlertInfo
from sentinel.api.deps import AppState, start_investigation
from sentinel.db.models import Incident

router = APIRouter()

_DEDUPE_WINDOW = timedelta(seconds=60)


class AlertmanagerBody(BaseModel):
    """The Alertmanager v4 notification body (grouped alerts)."""

    alerts: list[dict[str, Any]] = []
    status: str = "firing"


def _labels(alert: dict[str, Any]) -> dict[str, str]:
    return cast(dict[str, str], alert.get("labels", {}))


def _new_incident_id(state: AppState, name: str, service: str, alert: dict[str, Any]) -> UUID:
    with state.session_factory() as session:
        # Dedupe: same (alertname, service) within the window -> reuse the existing incident.
        window_start = datetime.now(UTC) - _DEDUPE_WINDOW
        existing = (
            session.query(Incident)
            .filter(
                Incident.alert_name == name,
                Incident.service == service,
                Incident.created_at >= window_start,
            )
            .order_by(Incident.created_at.desc())
            .first()
        )
        if existing is not None:
            return cast(UUID, existing.id)
        incident = Incident(
            alert_name=name,
            service=service,
            severity=_labels(alert).get("severity", "warning"),
            status="investigating",
            raw_alert=alert,
        )
        session.add(incident)
        session.commit()
        return incident.id


@router.post("/alerts/webhook", status_code=202)
async def alert_webhook(body: AlertmanagerBody, request: Request) -> dict[str, str]:
    """Accept an alert, create/dedupe an incident, and start the investigation."""
    state: AppState = request.app.state.sentinel
    if not body.alerts:
        return {"status": "no_alerts"}
    alert = body.alerts[0]
    name = _labels(alert).get("alertname", "unknown")
    service = _labels(alert).get("service", "unknown")
    incident_id = _new_incident_id(state, name, service, alert)

    alert_info = AlertInfo(
        name=name,
        service=service,
        severity=_labels(alert).get("severity", "warning"),
        raw=alert,
    )
    asyncio.create_task(start_investigation(state, str(incident_id), alert_info))
    return {"incident_id": str(incident_id), "status": "accepted"}
