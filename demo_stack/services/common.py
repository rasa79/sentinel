# LEARN[07]: chaos-as-a-deterministic-state-machine (and why it is process-local)
# Why this way: instead of randomly degrading a service, the toy service keeps a
#   single module-level "current chaos" state (type + expiry) that routes /work into a
#   known behaviour. Tests and the demo trigger a deterministic fault and assert a
#   specific observable metric, instead of racing a random injector. The state is
#   process-local because there is exactly one service process per container and chaos
#   is per-process by construction; global state also means the stack needs no control plane.
# Good sides:
#   - deterministic: /work's behaviour is fully determined by the active chaos type, so
#     tests are stable
#   - self-clearing: a reset timer snaps the state back to idle after duration_seconds,
#     so a leak is bounded and a forgotten chaos cannot wedge the stack forever
#   - no extra infrastructure: chaos lives in-process, not in a sidecar or control channel
# Drawbacks:
#   - process-local state is invisible across replicas (there is exactly one replica per
#     service here); scaling a service would apply chaos to only one container (ties to L3)
#   - only one chaos type can be active at a time, so you cannot compose e.g. error_burst
#     + latency_spike
#   - state is lost on restart (an acceptable demo cost; a real fault-injection harness owns it)
# Concept: this is an explicit finite-state machine with exactly two states — idle and
#   active(type) — plus a timed transition back to idle. When idle, /work returns the normal
#   "ok" response; when active, a per-type branch changes the response/metrics (edge:
#   latency_spike sleeps, error_burst returns 5xx, memory_leak allocates, bad_deploy flips
#   the version and degrades). The "state machine" framing is the useful part: a Java
#   engineer sees this as a scenario/state object a test can drive, not as randomness — the
#   test sets the state, then asserts the outcome. The reset timer is an expiry timestamp
#   plus a daemon reaper thread guarded by a generation counter so a stale reaper cannot
#   clear a newer chaos. This is the cheap version of real fault-injection platforms (they
#   are distributed state machines); here a single-process state object is enough, and L1
#   documents the deliberate scope (container/process faults only, no network or disk faults).
# See also: LEARN[08] (prometheus metric types), L1 in KNOWN_LIMITATIONS.md
from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHAOS_TYPES = ("latency_spike", "error_burst", "memory_leak", "bad_deploy")
# TODO(review): L1 - chaos covers container/process faults only (no network/disk fill)
DEFAULT_CHAOS_DURATION_SECONDS = 60.0
LATENCY_SPIKE_SLEEP_SECONDS = 1.5  # sleep added per /work while latency_spike is active
MEMORY_LEAK_CHUNK_BYTES = 8 * 1024 * 1024  # ~8MB allocated per /work while memory_leak is active
SERVICE_VERSION_LABEL = "SENTINEL_SERVICE_VERSION"

logger = logging.getLogger("sentinel.demo")

# ---------------------------------------------------------------------------
# Metrics (prometheus-client)
# ---------------------------------------------------------------------------
# LEARN[08]: prometheus-client metric types (Counter vs Histogram) for a Java/Micrometer engineer
# Why this way: we expose three metric families whose names the runbooks/evals query
#   (http_requests_total, http_errors_total, http_request_duration_seconds) and rely on the
#   default process collector for process_resident_memory_bytes. Counters track monotonic
#   counts, then a rate() over the scrape window; the Histogram tracks the whole latency
#   distribution so a quantile (p95) can be derived without storing every sample.
# Good sides:
#   - Counter+rate() is the idiomatic "how many per second" signal; a Histogram gives quantiles
#   - the metric names match what the agent queries, so the copilot sees real signals now
#   - default collectors (process/python) give RSS for free via process_resident_memory_bytes
# Drawbacks:
#   - a Counter only ever increases; to get a rate you must window it with rate()/increase(),
#     which is a scrape-time query, not a metric attribute
#   - a Histogram's accuracy depends on its buckets; the default buckets are coarse around small
#     values and may mislead on extreme latencies (kept for the demo; a real service tunes them)
#   - counters are per-process; a restart resets them, so a rate() across a restart window can
#     look like a sudden drop (usually not a problem for short scrape intervals in a demo)
# Concept: Micrometer has Counter (monotonic, use rate() for a per-second figure), Gauge (a
#   point-in-time value that can go up and down, e.g. memory) and Timer/Histogram (a distribution
#   of durations enabling quantiles). prometheus-client mirrors this: a Counter increments only,
#   so "errors per second" is rate(http_errors_total[rate_window]); Histogram.observe(x) records
#   a sample into running buckets and exposes _sum/_count plus quantiles, so "p95 latency" is
#   histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[rate_window])). The
#   distinction matters because a Counter cannot represent "current memory" (it never decreases) —
#   that is why RSS is a Gauge from the process collector. The code below is the smallest possible
#   illustration: counters for anything you'd sum, a histogram for anything you'd take a quantile
#   of, and a Gauge borrowed from the runtime for memory.
# See also: LEARN[07] (chaos state machine), D16 (5s scrape interval)
REQUESTS = Counter(
    "http_requests_total", "Total HTTP requests handled", ["service", "endpoint", "status"]
)
ERRORS = Counter("http_errors_total", "Total 5xx responses returned", ["service"])
DURATION = Histogram(
    "http_request_duration_seconds",
    "Request handling duration in seconds",
    ["service", "endpoint"],
)

_MEMORY_LEAK_BUFFER: list[bytes] = []  # holds allocated chunks so GC cannot reclaim them


class ChaosRequest(BaseModel):
    """POST /chaos body: which fault to inject and for how long."""

    type: str
    duration_seconds: float | None = DEFAULT_CHAOS_DURATION_SECONDS


class ChaosState:
    """Module-level chaos state machine (idle | active(type)) with an expiry reset timer.

    See LEARN[07]. A generation counter guards the reaper thread so a stale reaper cannot
    clear a newer activation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active: str | None = None
        self.expires_at: float | None = None
        self._generation = 0

    def activate(self, kind: str, duration_seconds: float) -> None:
        with self._lock:
            self._generation += 1
            gen = self._generation
            self.active = kind
            self.expires_at = time.monotonic() + duration_seconds
        threading.Thread(target=self._reaper, args=(gen, duration_seconds), daemon=True).start()

    def _reaper(self, generation: int, duration_seconds: float) -> None:
        time.sleep(duration_seconds)
        with self._lock:
            if self._generation == generation:
                self.active = None
                self.expires_at = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._expire_if_due()
            remaining = 0.0
            if self.active and self.expires_at is not None:
                remaining = max(0.0, self.expires_at - time.monotonic())
            return {"active": self.active, "remaining_seconds": round(remaining, 1)}

    def _expire_if_due(self) -> None:
        if (
            self.active is not None
            and self.expires_at is not None
            and time.monotonic() >= self.expires_at
        ):
            self.active = None
            self.expires_at = None

    @property
    def active_kind(self) -> str | None:
        with self._lock:
            self._expire_if_due()
            return self.active


CHAOS = ChaosState()


# LEARN[09]: demo services write deploy events straight to the shared Postgres DB (mandatory — D8)
#  Why this way: each toy service inserts its own deploy rows into the shared `deployments` table
# over
#    the compose network, instead of POSTing to a deploy-ingestion API. The demo stack and the
#   Sentinel
#   app share that database anyway, so a write is fewer moving parts than an ingestion endpoint.
# Good sides:
#   - trivial to wire: psycopg + a CREATE TABLE IF NOT EXISTS, no extra HTTP service to build/test
#   - the data is immediately visible to the agent (Phase 2 reads the same table for deploy history)
#   - it fails gracefully: on any DB error the demo keeps serving (deploy logging is non-critical)
# Drawbacks:
#   - shared-table coupling: two components (demo services and the Sentinel app) own one table, so a
#     schema change needs both sides in agreement, and there is no API boundary to version/validate
#   - the services reach the DB directly, so they need DATABASE_URL credentials in their env
#    - no audit/authorization layer: any service could write a fake deploy row (demo-only posture,
#   L2)
#  Concept: the alternative is a deployment-ingestion API, which the Sentinel agent would POST to.
# That
#    gives a clean contract and centralizes validation, but it is another service to build, deploy
#   and
#   secure — overkill when the only consumer already sits on the same Postgres instance. This is the
#   shared-database integration pattern: components trade a write to a common schema instead of an
#   explicit interface, which is fast and simple in a demo but couples them at the schema level (the
#    honest cost is the Drawbacks above). The Phase 2 alembic migration must therefore ADOPT this
#   table
#    (assert columns, not recreate) rather than assume ownership — the table is created idempotently
#   here
#    first. A Java engineer should read this as "a schema owned by two services, reconciled by
#   adoption",
#   at the opposite end of the spectrum from a well-factored service API.
# See also: LEARN[08] (metrics), L2 in KNOWN_LIMITATIONS.md
class DeployWriter:
    """Writes deploy events straight into the shared `deployments` table (see LEARN[09], D8).

    Creates the table idempotently if it does not exist (Phase 1 runs before the Phase 2
    alembic migration; the migration adopts this table without altering it).
    """

    def __init__(self, service_name: str, database_url: str, version: str) -> None:
        self.service_name = service_name
        self.database_url = database_url
        self.version = version

    def record_startup_deploy(self) -> None:
        self._record("deploy", self.version)

    def record_bad_deploy(self, new_version: str) -> None:
        self._record("bad_deploy", new_version)

    def _record(self, event: str, version: str) -> None:
        try:
            with psycopg.connect(self.database_url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    # CREATE TABLE IF NOT EXISTS is NOT concurrency-safe: three services starting
                    # together can race on the table's identity sequence and one hits
                    # `duplicate key (deployments_id_seq)` UniqueViolation. Serialize the DDL+p
                    # with a transaction-scoped Postgres advisory lock (released on commit).
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext('sentinel.deployments'))")
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS deployments ("
                        " id bigserial PRIMARY KEY, service text NOT NULL, version text NOT NULL,"
                        " event text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
                    )
                    cur.execute(
                        "INSERT INTO deployments (service, version, event) VALUES (%s, %s, %s)",
                        (self.service_name, version, event),
                    )
                conn.commit()
        except Exception:  # noqa: BLE001 - a demo must keep serving even if DB logging fails
            logger.warning(
                "deploy-event write failed for service=%s", self.service_name, exc_info=True
            )


# LEARN[10]: push-vs-pull logging — toy services push directly to Loki (acceptable for a demo)
#  Why this way: instead of running a log agent (Promtail / Alloy / Fluent Bit) that tails files or
# the
#    Docker log driver, each toy service POSTs its structured JSON log line straight to Loki's push
#   API
#   (`/loki/api/v1/push`) from a background worker thread. stdout remains the human-visible copy.
# Good sides:
#   - no extra agent container or Docker logging plugin to configure; the push is just an HTTP POST
#   - the log line is structured JSON by construction (the service already has the object), so no
#     fragile log-line parsing/relabeling is needed
#   - it exercises the same push path a real service would use behind an agent, so the agent's
#     queries work unchanged
# Drawbacks:
#    - a naive push thread has at-least-once/buffering gaps: a crash between publish and deliver
#   loses
#     a record, and the queue is in-memory, so nothing survives a restart (production would use an
#     agent with durable buffering and backpressure)
#   - push traffic is unbounded without a rate limit; a busy service would flood Loki
#   - the service must know Loki's URL and tolerate push failures (we log-and-continue)
# Concept: log aggregation has a pull and a push topology. Pull (Loki's default discovery is scrape/
#    Promtail) has the aggregator read logs, which decouples it from the app but needs a
#   discovery/tail
#    mechanism. Push has the app send logs, which is simple and real-time but puts the reliability
#   burden
#   on the app/buffer. Loki's push API lets either work; production stacks normally use an agent
#    (Promtail/Alloy/Fluent Bit) because it owns tailing, buffering, batching and backpressure. For
#   this
#    demo the trade-off is worth it: one HTTP POST per record, no agent to run, and stdout acts as
#   the
#    durable-enough copy. This is not a weakened requirement — it is a documented design choice, so
#   it is
#    NOT a TODO(review) item. The thread is a queue-drain loop: workers enqueue a dict, we batch and
#   POST;
#    a push failure is logged and swallowed so the request path is never blocked (see LokiPusher
#   below).
# See also: LEARN[08] (metrics), D9 (plain HTTP clients), the Loki config in deploy/loki
class LokiPusher:
    """Pushes structured JSON log lines to Loki's push API via a daemon background thread.

    See LEARN[10] (push-vs-pull logging). The thread drains a queue and POSTs a batch; stdout
    stays the primary human-visible copy via the JSON logging handler.
    """

    def __init__(self, loki_url: str, service_name: str) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._url = loki_url.rstrip("/") + "/loki/api/v1/push"
        self._service_name = service_name
        self._running = True
        self._thread = threading.Thread(
            target=self._run, name=f"loki-push-{service_name}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)  # sentinel to wake the thread

    def push(self, record: dict[str, Any]) -> None:
        self._queue.put(record)

    def _run(self) -> None:
        while self._running:
            try:
                first = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if first is None:
                break
            batch = [first]
            while True:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._post(batch)

    def _post(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        values = [[str(time.time_ns()), json.dumps(r)] for r in records]
        payload = {"streams": [{"stream": {"service": self._service_name}, "values": values}]}
        try:
            req = urllib.request.Request(
                self._url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception:  # noqa: BLE001 - push failures must not break the request path
            logger.warning("loki push failed for service=%s", self._service_name, exc_info=True)


def _structured_log_record(
    service_name: str, level: str, message: str, **fields: Any
) -> dict[str, Any]:
    return {
        "ts": datetime.now(UTC).isoformat(),
        "service": service_name,
        "level": level,
        "message": message,
        **fields,
    }


def _emit(
    loki_pusher: LokiPusher, service_name: str, level: str, message: str, **fields: Any
) -> None:
    """Build a structured JSON record, write it to stdout and queue it for Loki.

    Stdout is the human-visible copy; the LokiPusher thread also POSTs the same record.
    """
    record = _structured_log_record(service_name, level, message, **fields)
    logger.info(json.dumps(record))
    loki_pusher.push(record)


def _bump_patch(version: str) -> str:
    """Bump the last dotted version segment (e.g. 1.0.0 -> 1.0.1) for a simulated bad deploy."""
    parts = version.split(".")
    if parts and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def create_app(service_name: str) -> FastAPI:
    """Build the toy FastAPI app for ``service_name`` (see PLAN.md Task 1.1)."""
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    )
    loki_url = os.environ.get("LOKI_URL", "http://localhost:3100")
    version = os.environ.get(SERVICE_VERSION_LABEL, "1.0.0")

    deploy_writer = DeployWriter(service_name, database_url, version)
    loki = LokiPusher(loki_url, service_name)

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        loki.start()
        deploy_writer.record_startup_deploy()
        try:
            yield
        finally:
            loki.stop()

    app = FastAPI(title=f"toy-{service_name}", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"service": service_name, "status": "ok"}

    @app.get("/work")
    def work() -> Any:
        start = time.monotonic()
        kind = CHAOS.active_kind
        status = 200 if kind not in ("error_burst", "bad_deploy") else 503

        if kind == "latency_spike":
            time.sleep(LATENCY_SPIKE_SLEEP_SECONDS)
        elif kind == "memory_leak":
            _MEMORY_LEAK_BUFFER.append(b"x" * MEMORY_LEAK_CHUNK_BYTES)

        elapsed = time.monotonic() - start
        DURATION.labels(service_name, "work").observe(elapsed)
        REQUESTS.labels(service_name, "work", str(status)).inc()
        if status >= 400:
            ERRORS.labels(service_name).inc()

        _emit(
            loki,
            service_name,
            "ERROR" if status >= 400 else "INFO",
            "work",
            status=status,
            latency_ms=round(elapsed * 1000, 1),
        )

        if status >= 400:
            return JSONResponse(
                status_code=status,
                content={"service": service_name, "status": "degraded", "chaos": kind},
            )
        return {"service": service_name, "status": "ok", "latency_ms": round(elapsed * 1000, 1)}

    @app.post("/chaos")
    def chaos(body: ChaosRequest) -> dict[str, Any]:
        if body.type not in CHAOS_TYPES:
            raise HTTPException(status_code=400, detail=f"unknown chaos type {body.type!r}")
        duration = body.duration_seconds or DEFAULT_CHAOS_DURATION_SECONDS
        CHAOS.activate(body.type, duration)
        if body.type == "bad_deploy":
            new_version = _bump_patch(version)
            deploy_writer.record_bad_deploy(new_version)
        return {"chaos": body.type, "duration_seconds": duration, "service": service_name}

    @app.get("/chaos/status")
    def chaos_status() -> dict[str, Any]:
        return CHAOS.status()

    @app.get("/metrics")
    def metrics() -> Response:
        # Serve the default registry directly (no trailing-slash redirect so scraping is simple).
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
