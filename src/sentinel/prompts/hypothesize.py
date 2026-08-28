"""Hypothesis prompt (PLAN.md Task 3.2). Mirrors
:class:`sentinel.agent.schemas.RootCauseHypothesis`."""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

ROLE = "You are an SRE incident analyst investigating a service degradation."

TASK = (
    "Given the gathered evidence (logs, metrics, deploy events, runbook hits), form a root-cause "
    "hypothesis. Respond with ONLY a JSON object with the cause, a confidence in [0,1], a list of "
    "evidence strings, the affected service, and a list of references. The authoritative affected "
    "service is given as 'alert service=<name>'; use that name (not an endpoint or log-derived "
    "name) for affected_service and in the cause."
)

# Kept in lock-step with RootCauseHypothesis.model_json_schema() (drift-guard test).
HYPOTHESIS_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "cause": {"type": "string"},
            "confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "affected_service": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["cause", "confidence", "evidence", "affected_service", "references"],
    },
    indent=2,
)

FEW_SHOT_INPUT = (
    '{"evidence": "http_errors_total rising; deploy row with bad_deploy"} | alert service=orders'
)
FEW_SHOT_OUTPUT = json.dumps(
    {
        "cause": "A faulty release was deployed to the orders service.",
        "confidence": 0.85,
        "evidence": ["http_errors_total climbing", "bad_deploy row with new version"],
        "affected_service": "orders",
        "references": ["runbook: bad-deploy-rollback"],
    },
    indent=2,
)


def build_hypothesis_prompt(evidence_summary: str) -> str:
    """Build the hypothesis prompt from a condensed summary of the gathered evidence."""
    return (
        f"{ROLE}\n\n{TASK}\n\nJSON Schema:\n{HYPOTHESIS_SCHEMA}\n\n"
        f"Example input:\n{FEW_SHOT_INPUT}\nExample output (JSON only):\n{FEW_SHOT_OUTPUT}\n\n"
        f"Now respond with ONLY the JSON object for this evidence:\n{evidence_summary}\n"
    )
