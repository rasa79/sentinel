# Sentinel — Agentic Incident Triage Assistant (SRE Copilot)

*Status: Phase 0 — repo scaffold & tooling.* This README is a stub; it is expanded in
Phase 5 (demo section) and Phase 8 (full architecture + quickstart).

See `PLAN.md` for the authoritative implementation plan and the binding Working Protocol.

## Local model note

The plan names `qwen2.5:7b-instruct` as the local model. On this machine the configured
local model is **`phi4-mini`** (Ollama). All references to the local model use `phi4-mini`
instead; this is recorded as an environment note in the Phase 0 report.

## LLM setup (dual-provider smoke test)

The smoke test (`scripts/smoke_llm.py`) drives the same `structured_call` loop (D1) against the
configured provider. Provider is chosen by `LLM_PROVIDER=ollama|openai` (or `--provider`), and is
honored whether it is set in the shell or in `.env`:

**Local path (Ollama, default):**
- Install Ollama and run it bound to all interfaces: `OLLAMA_HOST=0.0.0.0 ollama serve`.
- Pull the model: `ollama pull phi4-mini` (this machine's local model; the plan originally
  named `qwen2.5:7b-instruct` — see the local-model note).
- Run the smoke test: `uv run python scripts/smoke_llm.py --provider ollama`.

**Cloud path (OpenAI-compatible):**
- Set `OPENAI_API_KEY` to a real key, `LLM_PROVIDER=openai`, and override the endpoint/model,
  e.g. `SENTINEL_LLM__BASE_URL=https://api.openai.com/v1` and `SENTINEL_LLM__MODEL=gpt-4o-mini`.
- Run: `uv run python scripts/smoke_llm.py --provider openai`.

The script exits `0` on a valid structured object, `1` if the provider was reached but returned
invalid output, and `2` with a clear message if the endpoint is unreachable. Unprefixed secrets
(e.g. `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) may be placed in `.env`; the config model tolerates
them (see `.env.example`).

## Known limitations

Pre-declared scope cuts and known weaknesses are tracked in
[`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) (user-visible items are summarized below). Review
markers (`TODO(review)`) are enforced live by the pre-commit protocol checker.

## Demo (Phase 5 stub)

Bring the full stack up (infra + the containerized API):

```
docker compose -f deploy/docker-compose.yaml --profile api up -d --build
```

Gate check (the container path, not just the in-process tests):

- `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health` → `200`.
- `uv run sentinel demo` runs to a terminal status against the containerized API (injects a fault,
  fires the webhook, waits for the human gate or a direct resolution, streams to `resolved`, prints
  the final report).

### Container config (env + URLs)

The API container gets its secrets and host-vs-container URLs from `deploy/docker-compose.yaml`:

- **Secret (never committed):** `env_file: ../.env` injects the repo-root `.env` (gitignored) into
  the container, so the LLM API key reaches the API. Compose's own `.env` auto-loading is for var
  **substitution** only and does *not* ship vars into the container — without `env_file:` the API
  builds a keyless OpenAI client and crashes with `Missing credentials`.
- **URL resolution (D4):** the demo/CLI runs on the **host** and reaches the infra via
  `localhost`/`900x` and the API via `localhost:8000`; the **container** reaches the same services
  by their compose service names. The `environment:` block therefore sets the container-appropriate
  URLs (`postgres:5432`, `loki:3100`, `prometheus:9090`). The LLM defaults to a public
  OpenAI-compatible endpoint; for a **local Ollama** model the container `base_url` must be
  `http://host.docker.internal:11434/v1` (see `extra_hosts`, LEARN[06]), whereas the host CLI uses
  `http://localhost:11434/v1`.

With the API up on `:8000`, the CLI also drives individual operations:

- `uv run sentinel incidents list` — list incidents (optionally `--status`).
- `uv run sentinel incidents show <id>` — an incident + ordered agent trace + graph state.
- `uv run sentinel incidents approve <id>` / `reject <id>` — resume a pending approval (D6).
- `uv run sentinel incidents watch <id>` — tail the SSE stream of node-by-node updates live.
- `uv run sentinel demo` — inject a fault and generate `/work` traffic so it manifests, fire the
  webhook, wait for approval, approve, watch to a terminal status, and print the final report.

The `demo` command currently orchestrates the Phase-5 flow against one running service (default
`orders` at `http://localhost:9001`); Phase 8 polishes it into the full scripted walkthrough.

## Runbook ingestion (RAG)

`uv run sentinel ingest-runbooks` chunks the `runbooks/` corpus (whole doc + per-`##`-section
chunks), embeds each with a local `all-MiniLM-L6-v2` model, and upserts into the `runbooks` table
(idempotent by content hash — re-running never duplicates). The model is downloaded **on first
ingest** into `./.cache` (gitignored), so the first run needs network access and a moment; later
runs reuse the cached model and are quick.

## Eval (Phase 7)

`uv run sentinel evals run --mode mock|live` runs the 8-incident eval dataset
(`evals/dataset/*.yaml`) through the real agent graph with canned tool outputs. `mock` is
deterministic (100% — the mock LLM answers from the ground truth, a self-test of the harness);
`live` uses the configured LLM.

Measured `live` accuracy (structural scoring: cause category + affected service + action; threshold
≥ 75%):

| Model | Runs (overall) | Passed ≥75% |
|-------|----------------|-------------|
| deepseek-v4-flash (baseline, weakest) | 38%, 75%, 62%, 38% | 1 / 4 |
| deepseek-v4-pro                        | 62%, 75%, 75%    | 2 / 3 |

Both DeepSeek models run in **thinking** mode (they return `reasoning_content`), which ignores the
`temperature` knob — so `temperature=0.0` does not force determinism and the live results vary
run-to-run. See L8 in `KNOWN_LIMITATIONS.md` for the live-eval reliability caveat.

- **L1 – Chaos suite scope:** only container/process-level faults; no network degradation or
  disk-fill in v1.
- **L2 – Demo-only security posture:** unauthenticated API endpoints and a mounted Docker socket
  in the API container.
- **L3 – Single-tenant / single process:** concurrent investigations are serialized indefinitely.
- **L4 – Fixed-window verification:** no statistical confirmation and no auto-rollback on flap.
- **L5 – Grafana optional:** present only behind a compose profile with no provisioned dashboards.
- **L6 – LangSmith no-op:** tracing/eval-upload to LangSmith is a logged no-op without a key
  (internal-only; not user-visible).
- **L7 – Partial scale emulation:** `scale_replicas` restarts named replica containers if present,
  else returns `not_applicable` (no compose v2 dynamic scaling, Phase 4).
