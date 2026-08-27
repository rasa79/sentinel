# LEARN[15]: extra="forbid" as a contract boundary against LLM hallucination
# Why this way: every structured payload the LLM produces is validated by a Pydantic model that is
#   configured with extra="forbid". If the model emits an extra key that the schema doesn't declare,
#   validation fails instead of silently dropping it.
# Good sides:
#   - a hallucinated key becomes a hard validation error (and a repair turn), not a silent data loss
#    - the agent graph never sees a field it didn't ask for, so downstream code can rely on the
#   schema
#   - it catches schema drift between the prompt's JSON block and the Python model (see LEARN[16])
# Drawbacks:
#    - a model that faithfully returns extra metadata now fails; you must re-prompt or accept the
#   failure
#    - it is a one-liner that does not teach — the reader must understand the failure mode it
#   prevents
#  Concept: "extra" controls what Pydantic does with keys not declared on the model. The default
# allows
#    them (extra="allow"); extra="ignore" silently drops them; extra="forbid" rejects them. When an
#   LLM
#    is the producer, the silent-drop option is the dangerous one: a model that invents
#   "root_cause_2"
#    or "confidence_override" would be silently discarded by the parser, and the graph would proceed
#   with
#    a partial record as if the model's extra intent never existed. That buries a real signal (the
#   model
#    thought the field was important) and lets drift creep in. By forbidding extras, a
#   schema-mismatched
#   model output fails loudly and loops back through the repair path (LEARN[04]), which is the right
#    place for the model to correct itself. A Java engineer should read this as a strict
#   DTO/deserializer
#   contract: Jackson's FAIL_ON_UNKNOWN_PROPERTIES, but turned on by default for LLM-produced data.
#  See also: LEARN[04] (structured output/repair), LEARN[16] (prompt schema block mirroring the
# model)
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    """All LLM-facing payloads forbid unknown keys so hallucinated fields fail loudly (see
    LEARN[15])."""

    model_config = ConfigDict(extra="forbid")


class AlertInfo(_StrictModel):
    """The mapped Alertmanager alert the agent investigates."""

    name: str
    service: str
    severity: str = "warning"
    raw: dict[str, Any] = Field(default_factory=dict)


class TriageResult(_StrictModel):
    """The LLM's initial classification: is this worth a full investigation and what is the
    target."""

    category: str
    summary: str
    severity: str
    affected_service: str | None = None
    investigate: bool = True


class LogExcerpt(_StrictModel):
    """A single log line pulled from Loki."""

    service: str
    message: str
    level: str = "info"
    timestamp: datetime | None = None


class MetricFinding(_StrictModel):
    """A metric anomaly from Prometheus, with the expression that produced it."""

    metric: str
    value: float
    breach: bool = False
    expression: str | None = None


class DeployEvent(_StrictModel):
    """A deploy event read from the shared deployments table."""

    service: str
    version: str
    event: str
    created_at: datetime | None = None


class RootCauseHypothesis(_StrictModel):
    """The agent's hypothesis for the root cause (task 3.3 nodes)."""

    cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    affected_service: str
    references: list[str] = Field(default_factory=list)


class RemediationProposal(_StrictModel):
    """A proposed remediation action (whitelisted action + target + params)."""

    action: str
    target_service: str
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str


class ExecutionResult(_StrictModel):
    """The outcome of actually running (or dry-running) a remediation action."""

    action: str
    target_service: str
    dry_run: bool
    status: str = "not_applicable"
    message: str | None = None


class VerificationResult(_StrictModel):
    """The result of re-checking the alerting expression after remediation (D15)."""

    resolved: bool
    attempts: int
    values: list[float] = Field(default_factory=list)


class IncidentReport(_StrictModel):
    """The final report an incident ends with."""

    summary: str
    hypothesis: RootCauseHypothesis | None = None
    remediation: RemediationProposal | None = None
    status: str = "resolved"
