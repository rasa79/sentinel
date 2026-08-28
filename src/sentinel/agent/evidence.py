"""Evidence-time semantics for the gather nodes (empty-is-suspicious retry).

The gather nodes (gather_logs / gather_metrics) run immediately after an alert fires. Because the
observability pipeline has lag — Prometheus scrapes every 5s (D16) and Loki push has its own delay
— an *active* fault may produce *zero* evidence on the very first query. This module provides the
bounded "empty-is-suspicious" retry used by both gather nodes, and reconciles it with LEARN[22]
(which says an empty query result is data, not an error).
"""

from __future__ import annotations

import time
from collections.abc import Callable

#  LEARN[28]: empty-is-suspicious vs empty-is-clean, and observability lag (mandatory deep-dive)
# Why this way: the alert fires the moment a fault is injected, but the evidence pipelines have not
# caught up — Prometheus scrapes every 5s (D16) and the demo services push logs to Loki on the
# request path, so the very first query can legitimately return `logs: []` and `rate(...)=0`. A
# gather node that takes that at face value concludes "false alert" for a fault that is actively
# producing errors. So the gather nodes do a short, bounded retry on empty *only while the
# investigation is for an active alert* (which is always true — the graph only runs because an alert
# fired), then fall back to treating empty as no-signal.
# Good sides:
#   - a fresh burst is not misread as "clean"; the investigation waits just long enough to observe
#     the fault
#   - the retry budget is bounded (3 attempts, ~3s apart) so the investigation cannot hang
#     indefinitely
#   - once evidence appears, retrying stops, so the added latency is proportional to the lag, not a
#     fixed tax (a healthy-but-alerting service that is genuinely quiet waits the full budget, which
#     is acceptable for an investigation that would otherwise produce a false negative)
# Drawbacks:
#   - a genuinely quiet false-positive alert waits ~6s before concluding "no signal"
#   - the retry is a heuristic, not a proof: if the evidence arrives after the budget, the
#     conclusion is still "no signal" (a real fleet would increase the budget or drive the decision
#     off the alert's own dedupe/metadata instead)
# Concept: the tension is between two readings of emptiness. LEARN[22] says an empty PromQL/Loki
# result is DATA — "this series has no samples in the window" — and that must never be an exception:
# the client maps it to a finding with breach=False / an empty log list so the caller can reason
# about absence. That is still true here; I am NOT describing "empty means error". What the gather
# node adds is the question of WHEN to accept that data. Under observability lag, empty-at-t=0 is
# not the same as empty-at-t=6s: the scraping/push hasn't caught the fault yet. So the node treats
# "empty during an active alert" as SUSPICIOUS (retry a few times) rather than DEFINITIVE
# (conclude). The reconciliation is a layered one: the client is always empty-as-data (LEARN[22]);
# the gather node is empty-is-suspicious for the lifetime of the active alert (retry briefly);
# and only after the retry budget expires does the no-signal reading win. A Spring engineer can
# think of this as a read-after-consistency problem: reading a CQRS read-model immediately after
# writing the cause races the eventual-consistency lag, so you poll the read model a little before
# trusting an empty read. Change the ordering (gather once, immediately) and the exact defect
# reproduces: an active fault is reported as a false alarm. That failure is not visible in the
# client code alone — it only appears at the graph/timing boundary, which is the restate test
# (QS-3).
# See also: LEARN[22] (empty results are data — the client side), LEARN[21] (retry for transient
# transport failures — this is a DIFFERENT retry: that one is for failed requests, this one is for
# empty-but-successful results), D16 (5s scrape), the gather nodes


def retry_while_empty[T](
    probe: Callable[[], T],
    is_empty: Callable[[T], bool],
    *,
    attempts: int = 3,
    interval_seconds: float = 3.0,
) -> T:
    """Run ``probe``; re-run it (up to ``attempts`` times total) while ``is_empty`` holds.

    Used by the gather nodes to ride out observability lag: an active fault may produce no signals
    on the first query, so we poll a short, bounded number of times before accepting the "empty
    result is data" reading (LEARN[22]). Once the result is non-empty we stop immediately.
    """
    result = probe()
    for _ in range(attempts - 1):
        if not is_empty(result):
            break
        time.sleep(interval_seconds)
        result = probe()
    return result
