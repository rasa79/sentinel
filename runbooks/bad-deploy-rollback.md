# Bad deploy — rollback guidance

## Symptoms

- A `bad_deploy` row appears in `deployments` (`select service, version, event from deployments where event='bad_deploy'`).
- `http_errors_total` rises around the deploy time; `http_requests_total{status="503"}` grows.
- `/work` is degraded while `/healthz` stays `ok`.
- The service version in the deployments table has a new patch (e.g. `1.0.1`) that does not behave.

## Likely causes

- The newly deployed version/configuration is faulty (a real bad release).
- An injected `bad_deploy` chaos fault that flips the version and degrades the service on purpose.
- A config or secret mismatch introduced at deploy time.

## Diagnostic steps

1. Read `deployments` for the most recent `bad_deploy` to confirm the offending version.
2. Check `/chaos/status` — an active `bad_deploy` is a deterministic fault.
3. Inspect the error rate and logs to confirm the degradation started at the deploy boundary.
4. Identify the last-known-good version (the `version` from the prior `deploy` row).

## Remediation options

- `rollback_deploy` — restart the container with the previous image tag recorded in `deployments`; this is the preferred remedy for a faulty release.
- `restart_service` — clears a degraded process state if the release is actually fine and the fault is transient.
- `no_action` — a deliberate demo `bad_deploy` resetting after its timer; only intervene if the deployment is real.
