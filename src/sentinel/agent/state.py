# LEARN[14]: LangGraph state (TypedDict + reducers) vs a Spring workflow-engine context object
#  Why this way: the agent graph passes state between nodes as a TypedDict. Each node returns a
# partial
#    update dict, and LangGraph merges it into the state channel (with per-key reducers if
#   configured)
#   rather than handing the whole context object around.
# Good sides:
#    - nodes are pure-ish functions of (state, config) -> partial update, which makes them testable
#   and
#     easy to reason about; state merging is explicit, not hidden behind a managed context bean
#    - the checkpoint persists the whole state snapshot between steps, so a long-running
#   investigation
#     survives a restart (see LEARN[19])
#   - selective updates (return only changed keys) keeps each node's contract narrow
# Drawbacks:
#    - a TypedDict is only a structure hint; it is not validated at runtime unless you add a reducer
#   /
#     validation, so a node can emit an ill-typed key and it silently merges
#   - the shared state is one flat dict, so data-model ownership is by convention, not by a bounded
#     context
# Concept: in a Java/Spring workflow engine (jBPM/Activiti) you often carry a mutable context object
#    (a session/process variables map) that every step reads and writes in place. LangGraph instead
#   uses
#   a functional state channel: the graph is a state machine whose "state" is reduced by each node's
#    returned partial update, like fold/reduce in functional programming. Every key in AgentState is
#   a
#   channel; returning {"hypothesis": h} from a node sets that channel; returning nothing leaves it
#    unchanged. Reducers let you define how overlapping updates combine (e.g. append to a list
#   channel
#   instead of overwrite); without a reducer a later node's update replaces the prior value. This is
#   exactly why the pattern works for checkpointing: the reduced state snapshot is the durable
#   "process variables", and LangGraph stores it after each node so it can resume mid-flow.
# See also: LEARN[15] (strict schemas), LEARN[19]/[20] (checkpointer and interrupt/resume)
from __future__ import annotations

from typing import TypedDict

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


class AgentState(TypedDict, total=False):
    """The LangGraph reduced state for one incident investigation.

    ``total=False`` so a fresh investigation has only the keys populated so far; LangGraph reduces
    each
    node's partial update into these channels (see LEARN[14]).
    """

    incident_id: str
    alert: AlertInfo
    triage: TriageResult | None
    logs: list[LogExcerpt]
    metrics: list[MetricFinding]
    deploys: list[DeployEvent]
    runbooks: list[RunbookHit]
    hypothesis: RootCauseHypothesis | None
    remediation: RemediationProposal | None
    approval: bool | None
    execution: ExecutionResult | None
    verification: VerificationResult | None
    report: IncidentReport | None
    errors: list[str]
    escalate: bool
