# LEARN[18]: what interrupt() actually does at a node (mandatory placement — D6, part 1 of 2)
# Why this way: the human-approval gate is a single call to interrupt(payload). The node contains NO
#   wait/sleep/poll loop; the graph just suspends and returns control to the caller.
# Good sides:
#   - the node stays a plain function; there is no busy-wait or thread blocked on a human
#   - LangGraph persists the state at the interrupt boundary, so a restart can resume the same wait
#   - the payload surfaces the proposal to the caller, and resume returns the human's decision
# Drawbacks:
#   - interrupt() unwinds the run: it raises out of the node, so code after the call is only reached
#     on resume (a subtle control-flow change a Java engineer may find surprising)
#   - the machinery (persist + resume) depends on the checkpointer being real and thread_id stable
#  Concept: in LangGraph, interrupt(value) does NOT block a thread waiting for input. Instead it
# raises a
#    special Interrupt signal that unwinds the whole run; LangGraph captures the current state
#   snapshot,
#    records that a "pending interrupt" exists, and returns control to whoever started the run.
#   Later you
#    resume with Command(resume=...), and LangGraph replays the graph up to the interrupt, where the
#   node
#    restarts and interrupt() now RETURNS the resume value — that value is the human's decision.
#   This is
#    cooperative suspension (like a coroutine yielding), NOT a blocking wait (like a thread sleeping
#   or an
#    @Async future get()). For a Java engineer this is closer to a BPMN human task / wait state than
#   to a
#    blocking Thread.sleep: the process is parked, durably, and the engine owns the resume. The node
#   has no
#    "waiting loop" because the engine does the waiting; the node just says "I need a decision" and
#   yields.
#   Part 2 of this topic (vs an API polling loop) lives alongside the checkpointer in LEARN[20].
#  See also: LEARN[20] (interrupt vs polling, deep-dive), LEARN[19] (checkpointer), LEARN[17] (DI
# via config)
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from sentinel.agent.state import AgentState


def human_gate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Suspend for a human decision on the proposed remediation (D6)."""
    proposal = state.get("remediation")
    payload = {
        "incident_id": state["incident_id"],
        "proposal": proposal.model_dump() if proposal else None,
    }
    decision = interrupt(payload)
    approved = (
        bool(decision.get("approved", False)) if isinstance(decision, dict) else bool(decision)
    )
    return {"approval": approved}
