# Disk pressure

## Symptoms

- The container or host reports low disk space; writes start to fail (read-only filesystem surface), and the service logs write errors.
- `/work` may begin returning server errors; Loki pushes or the deploy-event write (`deployments`) may start failing.
- The service may report `No space left on device` in its logs.

## Likely causes

- The container's writable layer or a mounted volume filled up (logs, temp files, or the Loki/Prometheus storage).
- Unbounded log growth without rotation.
- A large artifact or cache accumulation.

## Diagnostic steps

1. Check the container disk usage (`docker system df`, or inspect the mount) to confirm it is a capacity issue.
2. Identify what is consuming space: logs, temp files, or the metrics/log storage under the mount.
3. Confirm the failing operation (write path) via the structured logs.

## Remediation options

- `restart_service` — recreates the process and can clear transient temp/write state; does NOT free a full volume.
- `scale_replicas` — only if the pressure is per-container and a fresh instance avoids it.
- `no_action` — disk pressure is usually a platform concern; resolve by cleaning the volume or raising its size, then `restart_service` to recover the service.
