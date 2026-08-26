# Generic triage — first steps

## Symptoms

An alert has fired, but the specific signature is unknown. Start with the baseline health signals before digging into a specific category.

- `/healthz` — is the process up and reachable?
- `http_requests_total{service="..."}` and `http_errors_total{service="..."}` — traffic and error counts.
- `http_request_duration_seconds` — the latency distribution (p95) for the work path.
- `process_resident_memory_bytes` — memory pressure/leak trend.

## Likely causes

Any of: a bad deploy (`bad_deploy`), an error burst (`error_burst`), a latency spike (`latency_spike`), a memory leak (`memory_leak`), connection-pool exhaustion, disk pressure, or CPU contention.

## Diagnostic steps

1. Confirm the affected service and whether `/healthz` is healthy (process reachable but degraded work = application-level).
2. Check `/chaos/status` on the affected service — the demo injects deterministic faults; an active chaos type identifies the cause immediately.
3. Read the recent `deployments` rows for a just-deployed version.
4. Pull the structured logs from Loki for that service and the failing endpoint.
5. Inspect the three core signals above to classify the fault into one of the targeted runbooks.

## Remediation options

- `restart_service` — the most common first step to clear a transient degraded state.
- `rollback_deploy` — if the deploy history indicates a faulty release.
- `scale_replicas` — if load/demand or CPU contention is implicated.
- `no_action` — for a deliberate demo chaos fault that auto-resets; intervene only if the alert is real.
