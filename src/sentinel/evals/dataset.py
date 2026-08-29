"""Eval dataset loading + validation (PLAN.md Task 7.1 / D13).

Each dataset entry describes a known-root-cause incident: the alert that fires it, the ground-truth
cause (category + affected service), the expected remediation action, and the CANNED tool outputs
the gather nodes should return (so evaluation is deterministic and independent of the live stack).
"""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from sentinel.agent.schemas import DeployEvent, LogExcerpt, MetricFinding
from sentinel.rag.retrieve import RunbookHit

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_DIR = _REPO_ROOT / "evals" / "dataset"


class KnownCause(BaseModel):
    """Ground truth: which fault category + which service is affected."""

    model_config = ConfigDict(extra="forbid")

    category: str
    affected_service: str


class AlertSpec(BaseModel):
    """The alert labels (as the webhook would receive them)."""

    model_config = ConfigDict(extra="forbid")

    alertname: str
    service: str
    severity: str = "warning"


class ToolSpec(BaseModel):
    """Canned outputs for the gather/retrieval tools (deterministic, no live stack)."""

    model_config = ConfigDict(extra="forbid")

    logs: list[LogExcerpt] = []
    metrics: list[MetricFinding] = []
    deploys: list[DeployEvent] = []
    runbooks: list[RunbookHit] = []


class DatasetEntry(BaseModel):
    """One known-root-cause incident to evaluate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    chaos: str
    alert: AlertSpec
    known_cause: KnownCause
    expected_action: str
    tools: ToolSpec


def load_dataset(dataset_dir: Path | str = DEFAULT_DATASET_DIR) -> list[DatasetEntry]:
    """Load and validate every ``*.yaml`` entry in the dataset directory."""
    path = Path(dataset_dir)
    entries: list[DatasetEntry] = []
    for file in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        entry = DatasetEntry.model_validate(data)
        if entry.id in {e.id for e in entries}:
            raise ValueError(f"duplicate dataset id {entry.id!r}")
        entries.append(entry)
    return entries
