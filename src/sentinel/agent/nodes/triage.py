# LEARN[17]: dependency injection via LangGraph config["configurable"] vs constructor injection
# Why this way: LLM-backed nodes get their chat model from config["configurable"]["llm"] rather than
#    from a constructor or a global. LangGraph nodes are plain async functions (state, config) ->
#   dict;
#    they must be reconstructable/checkpointable, so they cannot take constructor args at compile
#   time.
# Good sides:
#   - tests inject a FakeLLM via config, so the same node code runs against a real model or a fake
#    - it keeps nodes pure-ish and serializable (the graph can be rebuilt and resumed — see
#   LEARN[19])
#   - it avoids a service locator/global; the dependency travels with the run
# Drawbacks:
#   - the dependency is implicit (a key in a dict), so a node that forgets it fails at runtime
#   - there is no compile-time guarantee the key is present; you must read it defensively
#  Concept: in a Spring app you inject a collaborator into a bean's constructor and the container
# wires
#    it. A LangGraph node cannot do that: nodes are stateless functions that LangGraph instantiates
#   per
#   step, and the whole graph (with its state) is what gets checkpointed and resumed later. So the
#    analog of "constructor injection" is passing a per-run "configurable" dict through the run
#   config,
#    and the node reads the collaborator it needs from there (the model, or any tool/event bus).
#   This is
#   more like a lightweight dependency-carrying context than Spring's IoC container — it favors
#   explicitness-at-the-call-site over a global bean registry, at the cost of being a dict you must
#    look up. The testability win is the point: the same node function is exercised identically with
#   a
#   real model (Phase 5+), a FakeLLM (unit tests), or the eval harness's canned LLM (Phase 7).
# See also: LEARN[18] (interrupt at the node level), LEARN[14] (state channels)
from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import TriageResult
from sentinel.agent.state import AgentState
from sentinel.llm.structured import structured_call
from sentinel.prompts.triage import build_triage_prompt


async def triage(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Classify the alert into an initial triage and set the affected service."""
    llm = config["configurable"]["llm"]
    alert = state["alert"]
    prompt = build_triage_prompt(alert.model_dump_json())
    result = structured_call(llm, prompt, TriageResult)
    return {"triage": result}
