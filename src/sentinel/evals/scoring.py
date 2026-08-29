"""Eval scoring (PLAN.md Task 7.2 / D13).

Accuracy is scored on STRUCTURE, not free-text similarity: a hypothesis is correct iff its affected
service matches the ground truth AND its free-text cause maps to the known fault category via a
small synonym table; a remediation is correct iff its action equals the expected action. See
LEARN[30].
"""

from __future__ import annotations

from sentinel.agent.schemas import RemediationProposal, RootCauseHypothesis
from sentinel.evals.dataset import KnownCause

# Check order matters: root-cause categories first so a "bad deploy caused errors" maps to
# bad_deploy (the cause), and a deploy-correlated error burst ("error burst after a deploy") still
# maps to error_burst because "error burst" precedes "deploy" in that phrasing.
_SYNONYM_ORDER: list[tuple[str, list[str]]] = [
    (
        "memory_leak",
        ["memory leak", "memory_leak", "resident memory", "rss", "oom", "heap", "memory"],
    ),
    (
        "latency_spike",
        [
            "latency spike",
            "latency_spike",
            "high latency",
            "latency",
            "slow",
            "p95",
            "response time",
        ],
    ),
    ("bad_deploy", ["bad deploy", "bad_deploy", "faulty release", "rollback"]),
    (
        "error_burst",
        ["error burst", "error_burst", "error rate", "http error", "5xx", "errors", "burst"],
    ),
]


def categorize_cause(cause: str) -> str | None:
    """Map a free-text root-cause string to one of the known fault categories (or None)."""
    text = cause.lower()
    for category, keywords in _SYNONYM_ORDER:
        if any(kw in text for kw in keywords):
            return category
    return None


def score_hypothesis(hypothesis: RootCauseHypothesis, known: KnownCause) -> bool:
    """Correct iff the affected service matches AND the cause maps to the known category."""
    service_ok = hypothesis.affected_service == known.affected_service
    return service_ok and categorize_cause(hypothesis.cause) == known.category


def score_remediation(remediation: RemediationProposal | None, expected_action: str) -> bool:
    """Correct iff the proposed action equals the expected action."""
    return remediation is not None and remediation.action == expected_action
