# Noisy neighbor — CPU contention

## Symptoms

- Latency spikes in `http_request_duration_seconds` (p95 climbs) without a concurrency or error cause.
- CPU saturation / throttling observed at the host or in the container metrics.
- `/healthz` remains `ok`, but `/work` gets slower; `http_requests_total` is steady.
- The histogram tail widens even though there is no corresponding error burst.

## Likely causes

- Another process or container on the same host is consuming CPU (a noisy neighbor).
- The host is under-provisioned for the current load (CPU steal / throttling).
- A CPU-heavy background job on the same node competing for cycles.

## Diagnostic steps

1. Confirm CPU is the bottleneck: check container CPU usage and host-level contention (steal/throttle).
2. Correlate the latency histogram (`histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`) with CPU pressure.
3. Rule out application-induced latency (no active `latency_spike` chaos, no slow downstream call).
4. Look for competing workloads on the node.

## Remediation options

- `scale_replicas` — spread the request load across more instances so each sees less CPU pressure.
- `restart_service` — clears a transient CPU-throttled state but does not fix host contention.
- `no_action` — if contention is from an external neighbor, resolve at the host level rather than restarting the service.
