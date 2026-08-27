"""Remediation prompt (PLAN.md Task 3.2). Mirrors
:class:`sentinel.agent.schemas.RemediationProposal`."""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

ROLE = "You are an SRE remediation planner."

TASK = (
    "Given the root-cause hypothesis, propose a single remediation action. Use only a whitelisted "
    "action (restart_service, rollback_deploy, scale_replicas, no_action) for the affected "
    "service. Respond with ONLY a JSON object with the action, target_service, an optional params "
    "object, and a one-line rationale."
)

# Kept in lock-step with RemediationProposal.model_json_schema() (drift-guard test).
REMEDIATION_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "target_service": {"type": "string"},
            "params": {"type": "object"},
            "rationale": {"type": "string"},
        },
        "required": ["action", "target_service", "rationale"],
    },
    indent=2,
)

FEW_SHOT_INPUT = '{"cause": "faulty release on orders"}'
FEW_SHOT_OUTPUT = json.dumps(
    {
        "action": "rollback_deploy",
        "target_service": "orders",
        "params": {},
        "rationale": "Revert to the last known-good image recorded in deployments.",
    },
    indent=2,
)


def build_remediation_prompt(hypothesis_summary: str) -> str:
    """Build the remediation prompt from a one-line summary of the hypothesis."""
    return (
        f"{ROLE}\n\n{TASK}\n\nJSON Schema:\n{REMEDIATION_SCHEMA}\n\n"
        f"Example input:\n{FEW_SHOT_INPUT}\nExample output (JSON only):\n{FEW_SHOT_OUTPUT}\n\n"
        f"Now respond with ONLY the JSON object for this hypothesis:\n{hypothesis_summary}\n"
    )
