"""Eval harness (PLAN.md Task 7.2 / D13).

Runs the real agent graph once per dataset entry, with the gather/retrieval tools STUBBED from the
entry's canned outputs (so evidence is deterministic and the stack is not touched) and the LLM in
one of two modes:

  - ``mock``: a deterministic stand-in that answers from the entry's ground truth (threshold 100%);

  - ``live``:  the configured real LLM (threshold >= 75%).

Mock mode separates harness bugs from model quality: if mock fails, the harness/routing is wrong,
not the model. See LEARN[30].
"""

#  LEARN[30]: eval design — deterministic mock vs live, structure scoring, small-N honesty (D13)
# Why this way: the harness runs the graph twice — once with a ``mock`` LLM that answers from the
# entry's ground truth (threshold 100%), once with the real configured LLM (``live``, threshold
# >=75%). This splits the failure space in two: if mock fails, the harness, the graph routing, or
# the canned tools are wrong — it is a test bug, not a model bug. If mock passes but live falls
# short, the model (or its prompt) is the problem. Without the mock mode you could not tell those
# apart: a live failure might be a harness bug, and you would "fix" the wrong thing.
# Good sides:
#   - mock is a fixed, deterministic reference; the whole suite is green/red with no run-to-run
#     noise
#   - live gives a real-model read cheaply (no dedicated eval infra, LangSmith is a no-op unless
#     keyed)
#   - scoring on STRUCTURE (affected service matches AND free-text cause maps to a known category
#     via a synonym table AND action equals expected) is robust to prose variation, unlike free-text
#     similarity which is noisy and threshold-dependent.
# Drawbacks:
#   - small N: 8 incidents is a smoke signal, not a benchmark; a single mis-bucket swings accuracy
#     by >10% (1/8 = 12.5%), so read the number as "the pipeline works", not as model quality.
#   - the synonym table is subjective: a pathological cause phrase could map to the wrong category,
#     and it is the ONLY thing linking free text to a category (a hidden coupling in the eval
#     design).
#   - live mode is only as good as the configured LLM + credential: with no reachable model it
#     cannot run (an environment limitation, not a harness defect — recorded as "not executed").
# Concept: two orthogonal concerns — "does the agent pipeline do the right thing?" (harness) and
# "does THIS model produce the right structured answer?" (model). A deterministic mock isolates the
# first. Structure scoring is the evaluator's version of the strict DTO contract (LEARN[15]): the
# model emits a structured object; we check the fields that matter (category, service, action)
# rather than judging prose, which is the difference between "graded by a rubric" and "graded by a
# similarity heuristic". Reading a small-N eval honestly means treating it as a canary: it tells you
# whether the pipeline reaches a correct structured decision at all, not whether the model is
# production-grade. The restate test (QS-3): a reader looking at the harness sees two modes and a
# synonym table, but NOT why mock must be 100% (it is the harness's own unit test against itself) or
# why a single bad entry is not a strong signal — that is the eval epistemology, visible only in the
# rationale.
# See also: LEARN[15] (strict DTOs), LEARN[04] (structured output), D13 in PLAN.md, risk R1

from __future__ import annotations

import importlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from sentinel.agent.graph import build_graph
from sentinel.agent.schemas import AlertInfo, RemediationProposal, RootCauseHypothesis
from sentinel.config import Settings
from sentinel.evals.dataset import DEFAULT_DATASET_DIR, DatasetEntry
from sentinel.evals.scoring import score_hypothesis, score_remediation
from sentinel.llm.factory import get_chat_model

logger = logging.getLogger(__name__)

# A cause keyword that maps back to each category via scoring._SYNONYM_ORDER.
_CATEGORY_KEYWORD = {
    "error_burst": "Error burst",
    "latency_spike": "High latency",
    "memory_leak": "Memory leak",
    "bad_deploy": "Bad deploy",
}

# Unique prompt markers (per prompts/*.py) so a fake LLM can route deterministically.
_MARKER_TRIAGE = "Classify the incoming alert"
_MARKER_HYPOTHESIS = "form a root-cause hypothesis"
_MARKER_REMEDIATE = "SRE remediation planner"
_MARKER_REPORT = "post-incident reporter"

# The tool entry points the harness overrides per entry, keyed by module + attribute name.
_TOOL_OVERRIDES: dict[str, str] = {
    "sentinel.agent.nodes.gather_logs": "query_logs",
    "sentinel.agent.nodes.gather_metrics": "query_anomalies",
    "sentinel.agent.nodes.gather_deploys": "query_deploys",
    "sentinel.agent.nodes.runbook_rag": "retrieve_runbooks",
}


def _category_phrase(category: str) -> str:
    return _CATEGORY_KEYWORD.get(category, category)


class _MockLLM:
    """A deterministic LLM stand-in that answers from the entry's ground truth."""

    def __init__(self, entry: DatasetEntry) -> None:
        self._entry = entry

    def invoke(self, prompt: str, **kwargs: object) -> AIMessage:  # noqa: ARG002
        spec = self._entry
        cause = (
            f"{_category_phrase(spec.known_cause.category)} in {spec.known_cause.affected_service}"
        )
        if _MARKER_TRIAGE in prompt:
            return AIMessage(
                content=json.dumps(
                    {
                        "category": spec.known_cause.category,
                        "summary": f"{cause} detected",
                        "severity": spec.alert.severity,
                        "affected_service": spec.known_cause.affected_service,
                        "investigate": True,
                    }
                )
            )
        if _MARKER_HYPOTHESIS in prompt:
            return AIMessage(
                content=json.dumps(
                    {
                        "cause": cause,
                        "confidence": 0.92,
                        "evidence": ["canned evidence"],
                        "affected_service": spec.known_cause.affected_service,
                        "references": ["runbook: canned"],
                    }
                )
            )
        if _MARKER_REMEDIATE in prompt:
            return AIMessage(
                content=json.dumps(
                    {
                        "action": spec.expected_action,
                        "target_service": spec.known_cause.affected_service,
                        "params": {},
                        "rationale": "canned remediation",
                    }
                )
            )
        if _MARKER_REPORT in prompt:
            return AIMessage(content=json.dumps({"summary": cause, "status": "resolved"}))
        raise AssertionError(f"no mock response for prompt: {prompt[:80]!r}")


def _stub_tools(entry: DatasetEntry, restore: list[tuple[Any, str, Any]]) -> None:
    """Point gather/retrieval modules at the entry's canned outputs (originals restored after)."""
    stubs = {
        "sentinel.agent.nodes.gather_logs": lambda *a, **kw: entry.tools.logs,
        "sentinel.agent.nodes.gather_metrics": lambda *a, **kw: entry.tools.metrics,
        "sentinel.agent.nodes.gather_deploys": lambda *a, **kw: entry.tools.deploys,
        "sentinel.agent.nodes.runbook_rag": lambda *a, **kw: entry.tools.runbooks,
    }
    for dotted, attr in _TOOL_OVERRIDES.items():
        mod = importlib.import_module(dotted)
        restore.append((mod, attr, getattr(mod, attr)))
        setattr(mod, attr, stubs[dotted])


def _restore_tools(restore: list[tuple[Any, str, Any]]) -> None:
    for mod, attr, original in restore:
        setattr(mod, attr, original)


@dataclass
class EvalResult:
    entry_id: str
    chaos: str
    hypothesis_ok: bool
    remediation_ok: bool
    hypothesis: RootCauseHypothesis | None
    remediation: RemediationProposal | None


def evaluate(entry: DatasetEntry, *, mode: str, settings: Settings | None = None) -> EvalResult:
    """Run the graph once for a dataset entry and score the produced hypothesis + remediation."""
    settings = settings or Settings()
    known = entry.known_cause

    llm: Any = _MockLLM(entry) if mode == "mock" else get_chat_model(settings)

    restore: list[tuple[Any, str, Any]] = []
    _stub_tools(entry, restore)
    try:
        graph = build_graph(MemorySaver())  # type: ignore[arg-type]
        config: dict[str, Any] = {
            "configurable": {
                "llm": llm,
                "thread_id": entry.id,
                "settings": settings,
                "dry_run": True,
                "event_bus": None,
            }
        }
        initial = {
            "incident_id": entry.id,
            "alert": AlertInfo(
                name=entry.alert.alertname,
                service=entry.alert.service,
                severity=entry.alert.severity,
                raw={},
            ),
        }
        result = graph.invoke(initial, config)
    finally:
        _restore_tools(restore)

    hypothesis = result.get("hypothesis")
    remediation = result.get("remediation")
    return EvalResult(
        entry_id=entry.id,
        chaos=entry.chaos,
        hypothesis_ok=bool(hypothesis and score_hypothesis(hypothesis, known)),
        remediation_ok=score_remediation(remediation, entry.expected_action),
        hypothesis=hypothesis,
        remediation=remediation,
    )


def _maybe_langsmith() -> None:
    """LangSmith is a logged no-op unless a key is configured (L6)."""
    # TODO(review): L6 - LangSmith upload is a logged no-op (internal-only); confirm this stays a
    # no-op and does not silently skip eval runs when a key IS configured.
    if os.environ.get("LANGSMITH_API_KEY"):
        logger.info("LANGSMITH_API_KEY set; runs would be uploaded (L6: currently a logged no-op).")
    else:
        logger.info("LangSmith not configured (L6); skipping run upload.")


def run_all(mode: str, dataset_dir: str | None = None) -> list[EvalResult]:
    """Evaluate every dataset entry and return the scored results."""
    from sentinel.evals.dataset import load_dataset

    _maybe_langsmith()
    entries = load_dataset(dataset_dir or DEFAULT_DATASET_DIR)
    return [evaluate(entry, mode=mode) for entry in entries]
