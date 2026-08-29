# KNOWN LIMITATIONS

> Pre-declared scope cuts and known weaknesses, tracked per the Deferred-Work Tracking Protocol.
> Each entry carries exactly one review marker whose location is either inline here (while the
> affected component does not yet exist — "satisfied-until-created") or in the code once the
> component exists. The protocol checker enforces exactly one marker per entry.

## L1 — Chaos suite covers container/process faults only (user-visible)

- **What this means:** The demo chaos injector (`demo_stack`) only exercises container- and
  process-level faults (latency spike, error burst, memory leak, bad deploy). There is no network
  degradation (e.g. Toxiproxy) and no disk-fill fault in v1.
- **Where partial coverage lives:** the chaos injector is `demo_stack/services/common.py`; the scope
  caveat is carried by the L1 review marker in that file.

## L2 — No authentication/authorization on API endpoints; Docker socket mounted (user-visible)

- **What this means:** Every API endpoint, including approvals, is unauthenticated, and the
  `sentinel-api` container mounts `/var/run/docker.sock`. This is a deliberate demo-only security
  posture, not production hardening.
- **Where partial coverage lives:** none (component `src/sentinel/api` not yet created).
- **TODO(review):** move this marker into `src/sentinel/api/deps.py` when the API exists (Phase 5)
  and confirm the Docker-socket mount comment.

## L3 — Single-tenant, single API process; no horizontal scaling (user-visible)

- **What this means:** Concurrent investigations are serialized through one process; there is no
  horizontal scaling, and concurrent runs share the single checkpointer.
- **Where partial coverage lives:** none (component `src/sentinel/api` not yet created).
- **TODO(review):** move this marker into `src/sentinel/api/app.py` when the API exists (Phase 5).

## L4 — Post-remediation verification is a fixed-window metric re-check (user-visible)

- **What this means:** Verification is a fixed-window re-query of the alerting expression after
  `verification.delay_seconds`, with no statistical/confirmation window and no auto-rollback on
  flapping.
- **Where partial coverage lives:** component `src/sentinel/agent/nodes/verify.py` (Phase 6); the
  accepted risk is named in LEARN[29] and its `review` marker lives at that file
  (mandatory-placement pairing rule).

## L5 — Grafana only an optional compose profile; no provisioned dashboards (user-visible)

- **What this means:** Grafana is present only behind an optional compose profile and ships no
  provisioned dashboards.
- **Where partial coverage lives:** none (component `deploy/grafana` not yet created).
- **TODO(review):** move this marker into `deploy/docker-compose.yaml` when the Grafana profile is
  defined (Phase x) and re-state the "no provisioned dashboards" caveat.

## L6 — LangSmith tracing/eval-upload is a no-op without LANGSMITH_API_KEY (internal-only)

- **What this means:** When `LANGSMITH_API_KEY` is unset, tracing and eval-upload are a logged
  no-op; the harness still runs and scores locally.
- **Where partial coverage lives:** `src/sentinel/evals/harness.py` (`_maybe_langsmith`); the
  accepted no-op is confirmed there and its `review` marker lives with it.

## L7 — scale_replicas is partially emulated on plain Docker (user-visible)

- **What this means:** `scale_replicas` cannot dynamically scale via compose v2; it restarts any
  named replica containers that already exist and otherwise returns `not_applicable`.
- **Where partial coverage lives:** the review marker is in `src/sentinel/tools/executor.py` (the
  `_scale` path); the limitation is enforced there.

## L8 — Live-mode eval reliability below the 75% threshold with the available DeepSeek reasoning model (user-visible)

- **What this means:** The eval harness is proven correct in `mock` mode (100% — the mock LLM answers
  from the entry's ground truth, so it is a plumbing/self-test), but `live` mode against the
  configured DeepSeek reasoning model does NOT reliably reach the plan's ≥75% threshold. Observed
  (8-incident structural scoring): `deepseek-v4-flash` → 38%/75%/62%/38% (1 of 4 runs ≥75%);
  `deepseek-v4-pro` → 62%/75%/75% (2 of 3 runs ≥75%). Both models run in THINKING mode (they return
  `reasoning_content`), and DeepSeek's thinking mode ignores the `temperature` knob, so
  `temperature=0.0` does not force determinism — live results vary run-to-run.
- **Where partial coverage lives:** none; the verified plumbing is `mock` mode + the harness
  (`src/sentinel/evals/harness.py`, LEARN[30]). The shortfall is model reasoning/sampling variance on
  the structured output task; a deterministic/local non-reasoning endpoint (the plan's `qwen2.5:7b`
  target, or thinking mode disabled) is needed before live can gate.
- **TODO(review):** L8 - treat live as a gate only once a deterministic or non-reasoning inference
  path is available (or rethink the threshold/model); do not lower the 75% threshold silently (plan
  D13/risk R1).
