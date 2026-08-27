"""Triage prompt (PLAN.md Task 3.2). Mirrors :class:`sentinel.agent.schemas.TriageResult`."""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

ROLE = "You are an SRE triage assistant for a demo microservices stack."

TASK = (
    "Classify the incoming alert. Produce a category, a one-line summary, a severity, the affected "
    "service (or null), and whether to investigate further. Respond with ONLY a JSON object."
)

#  Kept in lock-step with TriageResult.model_json_schema() (drift-guard test in
# tests/unit/test_prompts.py).
TRIAGE_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "summary": {"type": "string"},
            "severity": {"type": "string"},
            "affected_service": {"type": ["string", "null"]},
            "investigate": {"type": "boolean"},
        },
        "required": ["category", "summary", "severity", "investigate"],
    },
    indent=2,
)

FEW_SHOT_INPUT = '{"alert": "high latency on the orders service"}'
FEW_SHOT_OUTPUT = json.dumps(
    {
        "category": "latency_spike",
        "summary": "Orders service is slow; possible downstream latency.",
        "severity": "high",
        "affected_service": "orders",
        "investigate": True,
    },
    indent=2,
)


def build_triage_prompt(alert_json: str) -> str:
    """Build the triage prompt for a serialized Alertmanager alert."""
    return (
        f"{ROLE}\n\n{TASK}\n\nJSON Schema:\n{TRIAGE_SCHEMA}\n\n"
        f"Example input:\n{FEW_SHOT_INPUT}\nExample output (JSON only):\n{FEW_SHOT_OUTPUT}\n\n"
        f"Now respond with ONLY the JSON object for this alert:\n{alert_json}\n"
    )
