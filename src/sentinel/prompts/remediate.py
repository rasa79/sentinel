"""Remediation prompt (PLAN.md Task 3.2). Mirrors
:class:`sentinel.agent.schemas.RemediationProposal`."""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

ROLE = "You are an SRE remediation planner."

TASK = (
    "Given the root-cause hypothesis, propose a single remediation action for the affected "
    "service. "
    "Decide by the CAUSE: a deploy/release cause -> rollback_deploy; a latency spike, memory leak, "
    "transient process, or error-burst with no deploy correlation -> restart_service; a clear "
    "load/capacity cause -> scale_replicas; nothing actionable -> no_action. Never choose "
    "scale_replicas for a latency or memory cause. Use only a whitelisted action (restart_service, "
    "rollback_deploy, scale_replicas, no_action). Respond with ONLY a JSON object with the action, "
    "target_service, params, and a one-line rationale."
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

FEW_SHOT_INPUT = '{"cause": "resident memory climbing (memory leak) on payments"}'
FEW_SHOT_OUTPUT = json.dumps(
    {
        "action": "restart_service",
        "target_service": "payments",
        "params": {},
        "rationale": "Restart the service to reclaim the leaked resident memory.",
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
