# Error burst after a deploy

## Symptoms

- `http_errors_total` climbs sharply; `rate(http_errors_total[1m])` is non-zero and `http_requests_total{status="503"}` increases.
- `/work` returns 5xx (often 503) while `/healthz` stays `ok` (the process is reachable).
- Structured logs for the affected service are at level `ERROR` with the `work` message and a failing status.
- A `bad_deploy` row may appear in the `deployments` table with a bumped version.

## Likely causes

- A bad release just deployed (mismatch between the new version and the code it exercises).
- An injected `error_burst` or `bad_deploy` chaos fault.
- A systemic dependency failure surfaced as client errors.

## Diagnostic steps

1. Correlate the error start with a deploy: query `select service, version, event from deployments order by created_at desc`.
2. Check `/chaos/status` — an active `error_burst` is deterministic.
3. Inspect the `http_errors_total{service=...}` series and its `rate` to confirm the burst window.
4. Read the ERROR log lines from Loki to confirm the failing path is the work endpoint.

## Remediation options

- `rollback_deploy` — revert to the previous (known-good) image/version recorded in `deployments`.
- `restart_service` — if the fault is a transient bad state rather than a bad release.
- `no_action` — for a deliberate demo `error_burst`, the chaos auto-resets on its timer; use `scale_replicas` only if a real traffic burst is suspected.
