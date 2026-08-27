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

## Runbook ingestion (RAG)

`uv run sentinel ingest-runbooks` chunks the `runbooks/` corpus (whole doc + per-`##`-section
chunks), embeds each with a local `all-MiniLM-L6-v2` model, and upserts into the `runbooks` table
(idempotent by content hash — re-running never duplicates). The model is downloaded **on first
ingest** into `./.cache` (gitignored), so the first run needs network access and a moment; later
runs reuse the cached model and are quick.

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
