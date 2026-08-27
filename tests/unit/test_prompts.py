"""Drift-guard tests for the prompt schema blocks (PLAN.md Task 3.2)."""

from __future__ import annotations

import json

from sentinel.agent.schemas import (
    IncidentReport,
    RemediationProposal,
    RootCauseHypothesis,
    TriageResult,
)
from sentinel.prompts.hypothesize import HYPOTHESIS_SCHEMA, build_hypothesis_prompt
from sentinel.prompts.remediate import REMEDIATION_SCHEMA, build_remediation_prompt
from sentinel.prompts.report import REPORT_SCHEMA, build_report_prompt
from sentinel.prompts.triage import TRIAGE_SCHEMA, build_triage_prompt


def _properties_keys(schema_json: str) -> set[str]:
    return set(json.loads(schema_json)["properties"].keys())


def test_triage_schema_matches_model() -> None:
    assert _properties_keys(TRIAGE_SCHEMA) == set(
        TriageResult.model_json_schema()["properties"].keys()
    )


def test_hypothesis_schema_matches_model() -> None:
    assert _properties_keys(HYPOTHESIS_SCHEMA) == set(
        RootCauseHypothesis.model_json_schema()["properties"].keys()
    )


def test_remediation_schema_matches_model() -> None:
    assert _properties_keys(REMEDIATION_SCHEMA) == set(
        RemediationProposal.model_json_schema()["properties"].keys()
    )


def test_report_schema_matches_model() -> None:
    assert _properties_keys(REPORT_SCHEMA) == set(
        IncidentReport.model_json_schema()["properties"].keys()
    )


def test_prompts_embed_schema_and_few_shot_and_json_only() -> None:
    prompts = [
        build_triage_prompt('{"alert": "x"}'),
        build_hypothesis_prompt("evidence"),
        build_remediation_prompt("hypothesis"),
        build_report_prompt("summary"),
    ]
    for prompt in prompts:
        assert "JSON Schema" in prompt
        assert "Example output" in prompt
        assert "ONLY" in prompt.upper()
