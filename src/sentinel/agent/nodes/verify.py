"""Verify node — re-check the alerting expression after remediation (D15, Phase 6).

The Phase 3 stub is now a real fixed-window verification loop: wait ``verification.delay_seconds``,
then re-run the alerting expression up to ``verification.attempts`` times with a backoff between
re-checks. The first clear result resolves the incident; if it is still breaching after the budget,
the verification is escalated (and an ``escalation`` event carries the observed metric values).
See LEARN[29] for why we re-check on a bounded window rather than watch continuously.
"""

#  LEARN[29]: fixed-window re-checks vs continuous watch (mandatory deep-dive — D15)
# Why this way: after the remediation executes we re-query the alerting expression on a BOUNDED
# window — wait ``delay_seconds``, then check up to ``attempts`` times with a backoff between
# re-checks, and escalate if it is still breaching at the end. Lower case: we do NOT run a
# continuous watcher that polls for the whole incident lifetime.
# Good sides:
#   - a bounded re-check loop ends; there is no long-lived watcher to cancel, no growing state, and
#     it is deterministic (a fixed number of checks) rather than an unbounded poll
#   - the loop is cheap: a few instant PromQL queries, not a stream; and the window (delay +
#     attempts) comes from config, so an operator can tighten/loosen it without a code change
#   - escalation is a first-class outcome: when the window never clears, the verify node emits an
#     ``escalation`` event with the observed metric values and the report reflects it (Phase 5 fix)
# Drawbacks:
#   - the accepted risk (named here and pinned as L4): a fixed window cannot CONFIRM sustained
#     recovery — it only says "no breach in this window", so a slow or late recovery, or a recovery
#     followed by a flap, is misread. There is no error budget / sustained-recovery window and no
#     auto-rollback: if the alert clears for one check then re-breaches later, the incident is
#     marked resolved and the later breach starts a NEW incident. That is the L4 trade-off,
#     deliberately accepted for a demo and worth a production hard look.
#   - a cumulative-counter rate (rate(...[5m])) lingers minutes after a fault clears, so the
#     re-check window must be sized to THAT, not to the remediation (hence the configurable ``expr``
#     and a short window for recovery tests); a naive short window on a counter rate would
#     false-escalate.
# Concept: continuous watch means a process or supervisor keeps re-evaluating the metric while the
# incident is open, and only closes it after a STABLE stretch of recovery — the production pattern
# (sustained-recovery window, error budget, flap damping, auto-rollback on repeated flap). That is
# robust but expensive and stateful: a watcher must live for the incident lifetime, manage its own
# lifecycle/restart, and encode the "how long is long enough" heuristic somewhere. A fixed-window
# re-check instead treats verification as a one-shot batch step in the graph: wait a bounded time,
# sample a few times, and decide. It is the "try once, maybe twice, then escalate" of a human run
# through a runbook — simple, auditable, and good enough when the remediation is expected to clear
# the fault within the window. The restate test (QS-3): the code shows the loop structure, but NOT
# the correctness trade-off — that a single clear could be a fluke and a production system would
# require a sustained-recovery window; that is the L4 limitation and why the marker lives here.
# See also: LEARN[21] (retry for transient request failures — a DIFFERENT retry), LEARN[28]
# (empty-is-suspicious gather retry), D15 in PLAN.md, limitation L4

# TODO(review): L4 - fixed-window verification cannot confirm sustained recovery (no error budget /
# sustained-recovery window); a single clear may be a flapping recovery. Peer with LEARN[29].
from __future__ import annotations

import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from sentinel.agent.schemas import VerificationResult
from sentinel.agent.state import AgentState
from sentinel.config import Settings
from sentinel.tools.prometheus import instant_query

# Gap between re-checks once the initial delay has elapsed. Not a config knob on purpose (D15): only
# the total window (delay) and the attempt count are tunable, keeping the loop simple and bounded.
_RECHECK_BACKOFF_SECONDS = 5.0


def verify(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Re-check the alert; resolved on first clear, escalated if it keeps breaching."""
    settings = config["configurable"].get("settings") or Settings()
    event_bus = config["configurable"].get("event_bus")
    thread_id = config["configurable"].get("thread_id")
    # The expression must be for the incident's own service — a global `rate(...[5m])` placeholder
    # stays non-zero whenever ANY service has recent errors (LEARN[29] cross-ref D15). A config
    # override lets a per-incident re-check (e.g. a memory gauge) confirm recovery cleanly.
    service = state["alert"].service
    expr = settings.verification.expr or (f'rate(http_errors_total{{service="{service}"}}[5m])')

    delay = settings.verification.delay_seconds
    attempts = settings.verification.attempts
    # Post-remediation settle window: give the fault (and the scrape pipeline) time to clear/report.
    if delay > 0:
        time.sleep(delay)

    values: list[float] = []
    made = 0
    resolved = False
    for i in range(attempts):
        made += 1
        findings = instant_query(expr)
        values.append(max((f.value for f in findings), default=0.0))
        if not any(f.breach for f in findings):
            resolved = True
            break
        if i < attempts - 1:
            time.sleep(_RECHECK_BACKOFF_SECONDS)

    if not resolved and event_bus is not None and thread_id is not None:
        # The remediation did not clear the alert: emit an escalation event with the last values.
        event_bus.emit(thread_id, "verify", "escalation", {"status": "escalated", "values": values})

    return {"verification": VerificationResult(resolved=resolved, attempts=made, values=values)}
