# Connection pool exhaustion

## Symptoms

- The service logs `psycopg`/connection timeouts or "connection pool exhausted" errors.
- `http_errors_total` may rise for the work endpoint (server-side errors), and the Latency histogram `/work` shows a tail.
- `http_requests_total` stays high; the DB is reachable but slow to hand out connections.
- The `/healthz` endpoint stays `ok` (the process is alive; only DB-backed work degrades).

## Likely causes

- Too many concurrent DB requests for the pool size (a demand spike or a leak of connections).
- Slow queries holding connections long enough to starve the pool.
- A connection, pool, or DB-side limit that is too small for the load.

## Diagnostic steps

1. Confirm the errors are DB/connection related (grep the structured logs for `psycopg`, `pool`, `timeout`).
2. Check the DB for long-running queries or idle-in-transaction connections.
3. Look at the latency histogram tail (`histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`).
4. Correlate with `http_errors_total` to see whether the failed requests are the work endpoint.

## Remediation options

- `restart_service` — clears a wedged pool of stale connections.
- `scale_replicas` — spreads the connection demand across additional instances.
- `no_action` — if the pool pressure is transient (e.g. temporary load), wait for it to ease rather than restart.
