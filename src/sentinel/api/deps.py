"""FastAPI dependency container and the graph runner (PLAN.md Task 5.1/5.3).

Holds the long-lived collaborators (settings, session factory, checkpointer, compiled graph, LLM,
event bus) so routes and tests can inject a fake LLM / fake session without touching the wiring. The
graph is sync (PostgresSaver is sync-only), so each run is executed in a worker thread via
``asyncio.to_thread`` to avoid blocking the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.types import Command

from sentinel.agent.events import EventBus
from sentinel.agent.graph import build_graph, make_checkpointer
from sentinel.agent.schemas import AlertInfo
from sentinel.agent.state import AgentState
from sentinel.config import Settings
from sentinel.db.session import create_engine_from_url, make_session_factory
from sentinel.llm.factory import get_chat_model


@dataclass
class AppState:
    """The shared collaborators for one API process."""

    settings: Settings
    session_factory: Callable[[], Any]
    graph: Any
    event_bus: EventBus
    llm: BaseChatModel
    checkpointer: Any = None


def make_config(state: AppState, incident_id: str) -> dict[str, Any]:
    """Build the RunnableConfig used to invoke/resume the graph for one incident."""
    return {
        "configurable": {
            "llm": state.llm,
            "thread_id": str(incident_id),
            "settings": state.settings,
            "dry_run": state.settings.remediation.dry_run,
            "event_bus": state.event_bus,
        }
    }


def _derive_status(state: AgentState) -> str:
    report = state.get("report")
    if report is not None:
        return report.status or "resolved"
    if state.get("verification") is not None:
        return "verifying"
    if state.get("execution") is not None:
        return "remediating"
    if state.get("escalate"):
        return "escalated"
    if "__interrupt__" in state:
        return "awaiting_approval"
    return "investigating"


def _set_incident_status(state: AppState, incident_id: str, status: str) -> None:
    from sentinel.db.models import Incident

    with state.session_factory() as session:
        incident = session.get(Incident, __import__("uuid").UUID(incident_id))
        if incident is not None and incident.status != status:
            incident.status = status
            session.commit()


async def start_investigation(state: AppState, incident_id: str, alert: AlertInfo) -> None:
    """Run the graph to (or past) the human_gate interrupt on a worker thread."""
    config = make_config(state, incident_id)

    def _run() -> None:
        result = state.graph.invoke({"incident_id": str(incident_id), "alert": alert}, config)
        _set_incident_status(state, incident_id, _derive_status(result))

    await asyncio.to_thread(_run)


async def resume_investigation(state: AppState, incident_id: str, approved: bool) -> None:
    """Resume an interrupted graph with the human decision on a worker thread."""
    config = make_config(state, incident_id)

    def _run() -> None:
        result = state.graph.invoke(Command(resume={"approved": approved}), config)
        _set_incident_status(state, incident_id, _derive_status(result))

    await asyncio.to_thread(_run)


def build_app_state(settings: Settings | None = None) -> AppState:
    """Construct the AppState from settings (env > config.yaml > defaults)."""
    settings = settings or Settings()
    engine = create_engine_from_url(settings.database.url)
    session_factory = make_session_factory(engine)
    checkpointer = make_checkpointer(settings.database.url)
    graph = build_graph(checkpointer)
    return AppState(
        settings=settings,
        session_factory=session_factory,
        graph=graph,
        event_bus=EventBus(session_factory=session_factory),
        llm=get_chat_model(settings),
        checkpointer=checkpointer,
    )
