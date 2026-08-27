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


def _set_incident_status(state: AppState, incident_id: str, status: str) -> None:
    from sentinel.db.models import Incident

    with state.session_factory() as session:
        incident = session.get(Incident, __import__("uuid").UUID(incident_id))
        if incident is not None and incident.status != status:
            incident.status = status
            session.commit()


def _final_state(state: AppState, incident_id: str) -> AgentState:
    """Read the latest checkpoint's channel values (the reduced graph state)."""
    if state.checkpointer is None:
        return {}
    cp = state.checkpointer.get({"configurable": {"thread_id": incident_id}})
    return cp.get("channel_values", {}) if cp else {}


def _stream_and_emit(state: AppState, incident_id: str, graph_input: Any) -> bool:
    """Run the graph, emitting per-node events (D10). True if it suspended at an interrupt."""
    config = make_config(state, incident_id)
    interrupted = False
    for chunk in state.graph.stream(graph_input, config, stream_mode="updates"):
        for node, update in chunk.items():
            if node == "__interrupt__":
                interrupted = True
                continue
            if not isinstance(update, dict):
                continue
            payload = {k: _serialize(v) for k, v in update.items()}
            state.event_bus.emit(incident_id, node, "node_update", payload)
    return interrupted


async def start_investigation(state: AppState, incident_id: str, alert: AlertInfo) -> None:
    """Run the graph to (or past) the human_gate interrupt, emitting node events, in a thread."""

    def _run() -> None:
        interrupted = _stream_and_emit(
            state, incident_id, {"incident_id": str(incident_id), "alert": alert}
        )
        status = (
            "awaiting_approval" if interrupted else _derive_status(_final_state(state, incident_id))
        )
        _set_incident_status(state, incident_id, status)

    await asyncio.to_thread(_run)


async def resume_investigation(state: AppState, incident_id: str, approved: bool) -> None:
    """Resume interrupted graph with the human decision, emitting node events, in a thread."""

    def _run() -> None:
        _stream_and_emit(state, incident_id, Command(resume={"approved": approved}))
        status = "rejected" if not approved else _derive_status(_final_state(state, incident_id))
        _set_incident_status(state, incident_id, status)

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
