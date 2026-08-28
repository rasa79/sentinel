"""Report prompt (PLAN.md Task 3.2). Mirrors :class:`sentinel.agent.schemas.IncidentReport`."""

from __future__ import annotations

import json

PROMPT_VERSION = "1"

ROLE = "You are an SRE post-incident reporter."

TASK = (
    "Summarize the incident into a concise report. Include a summary, the root-cause hypothesis "
    "(optional), the remediation (optional), and a final status. Respond with ONLY a JSON object. "
    "The input carries an 'ACTUAL OUTCOME' line: base the summary on the ACTUAL execution and "
    "verification outcome there, not on the intended action. Never claim a remediation succeeded "
    "unless the actual outcome says the alert was resolved."
)

# Kept in lock-step with IncidentReport.model_json_schema() (drift-guard test).
REPORT_SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "hypothesis": {"type": "object", "nullable": True},
            "remediation": {"type": "object", "nullable": True},
            "status": {"type": "string"},
        },
        "required": ["summary", "status"],
    },
    indent=2,
)

FEW_SHOT_INPUT = (
    '{"cause": "faulty release", "action": "rollback_deploy"}'
    " | ACTUAL OUTCOME: execution(status=dry_run, message='would roll back to 1.0.0') | "
    "verification(resolved=True)"
)
FEW_SHOT_OUTPUT = json.dumps(
    {
        "summary": "Orders degraded after a bad deploy; the rollback was executed and the alert "
        "recovered.",
        "hypothesis": {"cause": "faulty release"},
        "remediation": {"action": "rollback_deploy", "target_service": "orders"},
        "status": "resolved",
    },
    indent=2,
)


def build_report_prompt(incident_summary: str) -> str:
    """Build the report prompt from a condensed incident summary."""
    return (
        f"{ROLE}\n\n{TASK}\n\nJSON Schema:\n{REPORT_SCHEMA}\n\n"
        f"Example input:\n{FEW_SHOT_INPUT}\nExample output (JSON only):\n{FEW_SHOT_OUTPUT}\n\n"
        f"Now respond with ONLY the JSON object for this incident:\n{incident_summary}\n"
    )
