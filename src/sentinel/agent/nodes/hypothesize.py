"""Hypothesis node — form a root-cause hypothesis from the gathered evidence (PLAN.md Task 3.3)."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import RootCauseHypothesis
from sentinel.agent.state import AgentState
from sentinel.llm.structured import structured_call
from sentinel.prompts.hypothesize import build_hypothesis_prompt


def _evidence_summary(state: AgentState) -> str:
    logs = [f"{e.level}: {e.message}" for e in state.get("logs", [])]
    metrics = [f"{m.metric}={m.value:.3f}" for m in state.get("metrics", [])]
    deploys = [f"{d.event} {d.version}" for d in state.get("deploys", [])]
    runbooks = [r.title for r in state.get("runbooks", [])]
    parts = ["logs=" + "; ".join(logs[-5:]), "metrics=" + "; ".join(metrics[-5:])]
    if deploys:
        parts.append("deploys=" + "; ".join(deploys[-5:]))
    if runbooks:
        parts.append("runbooks=" + "; ".join(runbooks))
    return " | ".join(parts)


async def hypothesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Build a root-cause hypothesis from the gathered evidence."""
    llm = config["configurable"]["llm"]
    prompt = build_hypothesis_prompt(_evidence_summary(state))
    hypothesis = structured_call(llm, prompt, RootCauseHypothesis)
    return {"hypothesis": hypothesis}
