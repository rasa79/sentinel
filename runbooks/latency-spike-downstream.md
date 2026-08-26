# Latency spike — downstream service slow

## Symptoms

- `http_request_duration_seconds` (histogram) p95 climbs well above the baseline; check
  `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`.
- `/work` responses slow down, but `/healthz` stays fast (the process is alive, the work path is slow).
- The `latency_ms` field in structured logs is elevated.
- `http_requests_total` may rise; `http_errors_total` stays flat unless the spike cascades to timeouts.

## Likely causes

- A slow downstream dependency (cache, DB, network) the service calls on its work path.
- A deliberate `latency_spike` chaos fault injected on this service.
- Resource contention on the host or a noisy neighbor starving CPU.

## Diagnostic steps

1. Confirm the scope: does the spike affect one service or all three? Use `rate(http_request_duration_seconds_count[5m])`.
2. Read the structured logs for the `latency_ms` field to see the per-request latency distribution.
3. Check `/chaos/status` on the affected service — an active `latency_spike` is a deterministic cause.
4. Look upstream: which endpoint or pool is the work path waiting on (Loki logs, DB pool stats).

## Remediation options

- `restart_service` — clears a transitory degraded state or a stuck latency fault.
- `scale_replicas` — spread load if the latency is demand-driven (only effective across replica containers).
- `no_action` — if this is a known deterministic chaos/demo fault, wait for it to reset rather than intervene.
