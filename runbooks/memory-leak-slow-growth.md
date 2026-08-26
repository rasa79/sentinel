# Memory leak — slow growth

## Symptoms

- `process_resident_memory_bytes` grows monotonically over time (a Gauge, per process: query by `instance`).
- The growth is steady and does not return to baseline; `process_resident_memory_bytes` rarely decreases.
- `/work` may allocate memory each call while `memory_leak` chaos is active, expanding RSS by the chunk size.
- No corresponding error rate increase, but the process may eventually be OOM-killed as memory approaches the container limit.

## Likely causes

- A per-request allocation that is retained (a growing cache / buffer that is never released).
- An injected `memory_leak` chaos fault that appends to an in-memory buffer on each call.
- A driver or library cache that grows unbounded.

## Diagnostic steps

1. Confirm the trend: sample `process_resident_memory_bytes` over a window (a `Gauge`, so use the change, not `rate`).
2. Check `/chaos/status` — an active `memory_leak` is deterministic.
3. Cross-reference `/work` volume and the container memory limit to gauge how close to an OOM the process is.
4. Look for retained-object growth in the logs or a heap/pprof dump if the container provides one.

## Remediation options

- `restart_service` — the reliable way to reclaim leaked memory and clear the retained buffer.
- `no_action` — if it is a bounded demo `memory_leak`, the chaos state resets but the allocated memory persists until restart; schedule a restart to reclaim.
- `scale_replicas` — will not reduce per-process RSS; prefer `restart_service`.
