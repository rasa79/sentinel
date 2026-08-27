# LEARN[21]: retry policy design — 3 attempts + exponential backoff, selective on transient (D9)
#  Why this way: the Loki/Prometheus clients retry connect/5xx errors with exponential backoff but
# never
#    retry 4xx. This single policy is used by both clients (Prometheus cross-references it via
#   LEARN[22]).
# Good sides:
#    - transient failures (host down, connection reset) recover automatically; permanent ones fail
#   fast
#   - a bounded budget (3 attempts) + backoff avoids hammering a struggling service
#   - 4xx is never retried, so a bad request doesn't loop pointlessly at the expensive query path
# Drawbacks:
#   - retrying a 5xx that is actually a sustained outage delays the failure by the backoff window
#   - a wrongly-classified exception (e.g. treating a 403 as transient) would retry needlessly
#  Concept: the crux is classifying failures into transient vs permanent. Transient means "the
# request
#    may succeed if retried" (connection refused, timeout, 502/503/504). Permanent means "retrying
#   will
#    not help — fix the request" (4xx: bad params, auth, not found). In Spring Retry you express
#   this with
#   a RetryPolicy that distinguishes retryable vs non-retryable exceptions; here we encode it as a
#    predicate that returns True only for httpx.TransportError (connect/timeout) and 5xx
#   HTTPStatusError,
#   and False for everything else (notably all 4xx). We also keep the retries bounded
#    (stop_after_attempt(3)) with exponential backoff (wait_exponential) and *reraise*, so the
#   caller sees
#    the real exception after the budget is spent rather than a swallowed result. Retrying a 4xx is
#   the
#    classic mistake: it multiplies a guaranteed failure and can look like an outage when it is
#   really a
#    bug in the query. Backoff exists so retries do not fire in a tight loop that adds load to an
#   already
#   struggling target.
# See also: LEARN[22] (PromQL / cross-reference), D9 in PLAN.md
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from sentinel.agent.schemas import LogExcerpt
from sentinel.config import Settings

logger = logging.getLogger(__name__)

# LogQL selector: the service stream, filtered to error/warn/exception level lines.
_SELECTOR = '|~ "(?i)error|warn|exception"'
_RETRIES = 3

_Params = dict[str, str | int | float | bool | None]


def _retryable(exc: BaseException) -> bool:
    """Retry only transient failures: transport (connect/timeout) errors and 5xx responses."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(
    stop=stop_after_attempt(_RETRIES),
    wait=wait_exponential(multiplier=1, min=0.5, max=4),
    retry=retry_if_exception(_retryable),
    reraise=True,
)
def _get_json(client: httpx.Client, url: str, params: _Params) -> dict[str, Any]:
    resp = client.get(url, params=params)
    resp.raise_for_status()
    return cast(dict[str, Any], resp.json())


def query_logs(
    service: str,
    since: timedelta,
    limit: int = 100,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> list[LogExcerpt]:
    """Query Loki for recent error/warn/exception log lines for ``service`` (D9)."""
    base_url = base_url or Settings().loki.url
    client = client or httpx.Client(timeout=5.0)
    end = datetime.now(UTC)
    start = end - since
    params: _Params = {
        "query": f'{{service="{service}"}} {_SELECTOR}',
        "start": int(start.timestamp() * 1e9),
        "end": int(end.timestamp() * 1e9),
        "limit": limit,
        "direction": "backward",
    }
    payload = _get_json(client, f"{base_url.rstrip('/')}/loki/api/v1/query_range", params)

    logs: list[LogExcerpt] = []
    for stream in payload.get("data", {}).get("result", []):
        for value in stream.get("values", []):
            line = value[1]
            try:
                record = json.loads(line)
                logs.append(
                    LogExcerpt(
                        service=record.get("service", service),
                        message=record.get("message", line),
                        level=record.get("level", "info"),
                    )
                )
            except json.JSONDecodeError:
                logs.append(LogExcerpt(service=service, message=line, level="info"))
    return logs
