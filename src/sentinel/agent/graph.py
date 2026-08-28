# LEARN[19]: the Postgres checkpointer vs an in-memory saver (mandatory deep-dive — D5)
# Why this way: the graph is compiled against a PostgresSaver (langgraph-checkpoint-postgres) with a
#   psycopg pool, and thread_id is set to the incident's stable UUID. That makes every investigation
#   durable and resumable across process restarts.
# Good sides:
#    - the checkpoint (a state snapshot + any pending interrupt) survives a process kill, so an
#   in-flight
#     approval is not orphaned; the same incident can resume after a restart
#   - thread_id scoping means multiple incidents' checkpoints coexist without collision
#   - PostgresSaver.setup() creates the checkpoint tables idempotently at startup
# Drawbacks:
#   - a DB round-trip per node adds latency; an in-memory saver is far cheaper
#   - the checkpointer is a single writer, so concurrent resumes on the same thread are serialized
#    - if you forget thread_id (or use a non-stable id) the checkpoint is keyed wrong and resume
#   breaks
#  Concept: a checkpoint is NOT just the current state — LangGraph also records the control position
# and
#    any pending interrupt, so a graph can be re-loaded at exactly the point it yielded.
#   PostgresSaver
#   persists that to the `checkpoints`/`checkpoint_writes` views (setup() creates them), keyed by
#   thread_id + a checkpoint id. Because the store is the database, the graph object itself can be
#    discarded and rebuilt later (a process restart) and still resume: you just build a new graph
#   over a
#    new pool against the same DB and reuse the same thread_id. With an in-memory saver, the
#   checkpoint
#    lives in RAM; a restart loses it, so a human approval that was pending when the process died
#   becomes
#    orphaned (there is no way to know what was waiting). That is exactly why the plan pins a
#   DB-backed
#    saver and why thread_id must be the stable incident id (incident.id) — otherwise the checkpoint
#   is
#    associated with a run, not with the incident, and a re-launched incident can't find its own
#   state.
#    This is the durable workflow-engine persistence a Java team expects from a jBPM/Activiti job
#   store.
# See also: LEARN[20] (interrupt vs polling), LEARN[14] (state channels), Task 3.4 integration test
# ---------------------------------------------------------------------------
# LEARN[20]: LangGraph interrupt/Command(resume) vs an API polling loop (mandatory deep-dive — D6)
# Why this way: a human-approval gate uses LangGraph interrupt() (LEARN[18]) and resumes with
#   Command(resume=...), instead of an API-level polling loop that re-checks the incident status.
# Good sides:
#   - the graph suspends at one durable point; there is no re-implemented "waiting" state machine
#   - single-writer semantics (the checkpointer) avoid two paths racing to update the same incident
#   - the resume carries the decision directly and the graph continues deterministically
# Drawbacks:
#   - the interrupt machinery is LangGraph-specific and requires the DB checkpointer to be real
#   - you must go through the graph to approve; a naive REST polling approach is more familiar
# Concept: the naive approach is a polling loop in the API: when an incident is awaiting approval, a
#    thread/loop repeatedly reads the incident status and, when it changes, advances the workflow.
#   That
#    re-implements the workflow engine's "wait state" by hand and is racy (who owns the transition?)
#   and
#    non-durable (a crash mid-poll loses the intended advance). LangGraph instead treats a human
#   task as a
#   first-class function call that suspends the run: the graph yields (interrupt), the state is
#   checkpointed, and resume re-enters the graph via Command(resume=<decision>). The suspension is
#   cooperative and durable — the engine owns the wait state and the transition, exactly like a BPMN
#    human-task/wait-state where the workflow engine parks the process and an external signal
#   resumes it.
#    You don't poll; you signal. The single-writer checkpointer also means the API's approve
#   endpoint and
#   the graph can't both advance the incident: the resume is the one authoritative transition.
# See also: LEARN[18] (interrupt at a node), LEARN[19] (checkpointer) — the polling-vs-interrupt
#   comparison lives here; Task 3.4 integration test round-trips this through a real checkpointer
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from sentinel.agent.nodes.execute import execute
from sentinel.agent.nodes.gather_deploys import gather_deploys
from sentinel.agent.nodes.gather_logs import gather_logs
from sentinel.agent.nodes.gather_metrics import gather_metrics
from sentinel.agent.nodes.human_gate import human_gate
from sentinel.agent.nodes.hypothesize import hypothesize
from sentinel.agent.nodes.remediate import remediate
from sentinel.agent.nodes.report import report
from sentinel.agent.nodes.runbook_rag import runbook_rag
from sentinel.agent.nodes.triage import triage
from sentinel.agent.nodes.verify import verify
from sentinel.agent.state import AgentState


def _should_investigate(state: AgentState) -> str:
    triage_result = state.get("triage")
    return "gather_logs" if triage_result is not None and triage_result.investigate else "report"


def _needs_approval(state: AgentState) -> str:
    remediation = state.get("remediation")
    return (
        "human_gate" if remediation is not None and remediation.action != "no_action" else "report"
    )


def _approval_route(state: AgentState) -> str:
    return "execute" if state.get("approval") else "report"


def build_graph(checkpointer: PostgresSaver | None = None) -> Any:
    """Explicitly wire the investigation graph (no dynamic node/edge generation)."""

    graph = StateGraph(AgentState)
    # Nodes
    graph.add_node("triage", triage)
    graph.add_node("gather_logs", gather_logs)
    graph.add_node("gather_metrics", gather_metrics)
    graph.add_node("gather_deploys", gather_deploys)
    graph.add_node("runbook_rag", runbook_rag)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("remediate", remediate)
    graph.add_node("human_gate", human_gate)
    graph.add_node("execute", execute)
    graph.add_node("verify", verify)
    graph.add_node("report", report)

    # Edges (explicit + named conditionals)
    graph.add_edge(START, "triage")
    graph.add_conditional_edges(
        "triage", _should_investigate, {"gather_logs": "gather_logs", "report": "report"}
    )
    # The evidence-gather path is UNCONDITIONAL and always runs all three gather nodes in order
    # (gather_logs -> gather_metrics -> gather_deploys). None of them is gate-controlled; the
    # decision to investigate was already made at `triage` above (the only conditional here). So
    # a run that reaches gather_logs ALWAYS reaches gather_metrics and gather_deploys — there is no
    # "skip metrics because logs arrived first" path. Each node decides empty-vs-signal itself
    # (LEARN[28]); gather_metrics is never skipped based on gather_logs.
    graph.add_edge("gather_logs", "gather_metrics")
    graph.add_edge("gather_metrics", "gather_deploys")
    graph.add_edge("gather_deploys", "runbook_rag")
    graph.add_edge("runbook_rag", "hypothesize")
    graph.add_edge("hypothesize", "remediate")
    graph.add_conditional_edges(
        "remediate", _needs_approval, {"human_gate": "human_gate", "report": "report"}
    )
    graph.add_conditional_edges(
        "human_gate", _approval_route, {"execute": "execute", "report": "report"}
    )
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", "report")
    graph.add_edge("report", END)

    return graph.compile(checkpointer=checkpointer)


def make_serde() -> Any:
    """Build the checkpoint serializer with the agent's Pydantic types registered.

    LangGraph's JsonPlusSerializer warns on unregistered types and will BLOCK them in a future
    version. Our state holds only schemas from sentinel.agent.schemas + RunbookHit, so we register
    exactly those classes; standard types (str/datetime/UUID/bool/list/dict) are always allowed.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from sentinel.agent.schemas import (
        AlertInfo,
        DeployEvent,
        ExecutionResult,
        IncidentReport,
        LogExcerpt,
        MetricFinding,
        RemediationProposal,
        RootCauseHypothesis,
        TriageResult,
        VerificationResult,
    )
    from sentinel.rag.retrieve import RunbookHit

    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            AlertInfo,
            TriageResult,
            LogExcerpt,
            MetricFinding,
            DeployEvent,
            RootCauseHypothesis,
            RemediationProposal,
            ExecutionResult,
            VerificationResult,
            IncidentReport,
            RunbookHit,
        ]
    )


def make_checkpointer(database_url: str) -> PostgresSaver:
    """Create a PostgresSaver over a psycopg pool and run setup() (idempotent)."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url,
        open=False,
        min_size=1,
        max_size=4,
        kwargs={"row_factory": dict_row, "autocommit": True},
    )
    pool.open()
    saver = PostgresSaver(pool, serde=make_serde())  # type: ignore[arg-type]
    saver.setup()
    return saver


# Re-exports for callers that just need the graph types.
__all__ = ["build_graph", "make_checkpointer", "make_serde", "AgentState"]
