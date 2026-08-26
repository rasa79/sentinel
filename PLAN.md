# Sentinel — Implementation Plan

**Project:** Agentic Incident Triage Assistant (SRE Copilot)
**Executor:** DeepSeek coding harness
**Repo root:** `~/dev2/Sentinel` on the **WSL2 native filesystem** (ext4 inside the WSL2 VM) — NOT `/mnt/c/Users/bucko/dev2/...`. Edited from Windows via the editor's WSL remote mode. Rationale: `/mnt/c` access is slow for uv/pytest/ruff (9P protocol overhead), and the Windows↔WSL2 boundary causes CRLF line-ending and executable-bit problems that break pre-commit hooks and shell scripts (mandatory LEARN topic in Task 0.1, decision D17). All paths below are repo-relative POSIX paths; all commands run inside WSL2.
**Plan version targets:** Python 3.12+, all dependency versions below were verified against PyPI on 2026-08-26.

---

## 1. Design Decisions (fixed — do not reopen during execution)

| #   | Decision                      | Choice                                                                                                                                                                                                                           | One-line rationale                                                                                                                                                                    |
| --- | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Structured output             | **Uniform JSON prompt → extract → Pydantic-validate → repair loop** (max 2 retries → escalate), implemented once in `src/sentinel/llm/structured.py`; do **not** use `with_structured_output`                                    | Weakest-link design: must work identically with a 7B local model, so one code path to test and reason about                                                                           |
| D2  | Embeddings                    | **sentence-transformers `all-MiniLM-L6-v2` (384-dim) run locally in both LLM modes**                                                                                                                                             | RAG is a pure retrieval concern; decoupling it from the LLM provider keeps the pgvector schema (fixed dim) and retrieval quality identical across cloud/local modes and works offline |
| D3  | LLM client                    | `langchain-openai` `ChatOpenAI` with configurable `base_url`/`api_key`/`model`                                                                                                                                                   | One client serves OpenAI-compatible cloud APIs and Ollama `/v1` unchanged                                                                                                             |
| D4  | Ollama topology               | Ollama runs on the **host**; containers reach it via `host.docker.internal:11434` (compose `extra_hosts: host-gateway`); Ollama started with `OLLAMA_HOST=0.0.0.0`                                                               | Spec requires host-side Ollama; `localhost` inside a container is the container, not the host                                                                                         |
| D5  | Checkpointing                 | `langgraph-checkpoint-postgres` `PostgresSaver` with a `psycopg` connection pool; `thread_id = str(incident.id)`                                                                                                                 | Survives restarts, enables interrupt/resume from the API process, single source of truth                                                                                              |
| D6  | HITL                          | LangGraph `interrupt()` inside `human_gate` node; resume with `Command(resume=...)` from the approval endpoint, same process + same checkpointer                                                                                 | `interrupt`/`Command` is the supported first-class mechanism; polling state would re-implement it badly                                                                               |
| D7  | DB migrations                 | **Alembic** for app schema; checkpoint tables created by `PostgresSaver.setup()` at startup                                                                                                                                      | Alembic is the standard (≈ Flyway/Liquibase for the Java-minded owner); checkpoint schema is owned by the library                                                                     |
| D8  | Deploy-event logging          | Toy services insert into the `deployments` table **directly over the shared compose Postgres**                                                                                                                                   | Fewer moving parts than a deploy-ingestion API; demo stack and sentinel share the network anyway                                                                                      |
| D9  | Loki/Prometheus clients       | Plain `httpx` + `tenacity` against `/loki/api/v1/query_range` and `/api/v1/query_range`                                                                                                                                          | Queries are few and fixed; no extra client-library abstraction to learn                                                                                                               |
| D10 | Streaming                     | **SSE** via `sse-starlette`, fed by an in-process `asyncio` pub/sub event bus; every event also persisted to `agent_events`                                                                                                      | Single-process app; WebSocket adds lifecycle complexity for zero demo gain                                                                                                            |
| D11 | Remediation executor          | `docker` Python SDK against the mounted `/var/run/docker.sock`, whitelist enforced in code + config, `dry_run` default **true**                                                                                                  | Reversible, auditable, and safe by default; dry-run proves the path before any mutation                                                                                               |
| D12 | CLI                           | `typer` + `rich`, entry point `sentinel` (e.g. `uv run sentinel demo`)                                                                                                                                                           | Minimal UI requirement; CLI is explicitly acceptable per spec                                                                                                                         |
| D13 | Evals                         | Harness supports `--mode mock` (canned LLM responses, deterministic, threshold **100%**) and `--mode live` (real LLM, threshold **≥ 75%**, i.e. ≥ 6/8)                                                                           | Mock mode validates plumbing deterministically; live mode measures real model quality with headroom for local models                                                                  |
| D14 | Config                        | `pydantic-settings`: `config.yaml` as base, env vars (`SENTINEL_*`, plus passthrough `LLM_PROVIDER`) override                                                                                                                    | One typed config object, zero code change between modes                                                                                                                               |
| D15 | Post-remediation verification | Wait `verification.delay_seconds` (default 30), re-query the alerting PromQL expression `verification.attempts` (default 3) times; on failure set incident `status=escalated` and emit event — **no second approval loop in v1** | Spec asks for auto-escalation on failure, not auto-retry; keeps the graph linear and readable                                                                                         |
| D16 | Demo observability            | Prometheus scrape interval **5s** in demo config                                                                                                                                                                                 | Short anomaly windows make metric-based detection/verification reliable in a demo                                                                                                     |
| D17 | Repo location & VCS           | Repo lives on the **WSL2 native filesystem** (`~/dev2/Sentinel`); git from Task 0.1 with per-task commits and per-phase tags                                                                                                     | `/mnt/c` is slow (9P overhead) and causes CRLF/executable-bit breakage; the protocol checker is a pre-commit hook, so git discipline is load-bearing, not optional                    |

---

## 2. Dependency List (pinned, verified against PyPI 2026-08-26)

`pyproject.toml` dependencies:

```
langgraph==1.2.11
langgraph-checkpoint-postgres==3.1.2
langchain-core==1.6.0
langchain-openai==1.6.0
pydantic==2.13.4
pydantic-settings==2.15.0
fastapi==0.141.1
uvicorn==0.52.4
sse-starlette==3.4.8
httpx==0.28.1
psycopg[binary,pool]==3.3.4      # pulls psycopg-pool==3.3.1
pgvector==0.5.0
alembic==1.19.1
pyyaml==6.0.3
tenacity==9.1.4
docker==7.2.0
typer==0.27.1
rich==15.0.0
sentence-transformers==6.0.0
langsmith==0.11.1                # optional; graceful no-op without LANGSMITH_API_KEY
```

dev-dependencies:

```
pytest==9.1.1
pytest-asyncio==1.4.0
ruff==0.16.4
mypy==2.3.1
pre-commit==4.6.2
```

Container images (pinned in compose): `pgvector/pgvector:pg16`, `prom/prometheus:v3.5.0`, `grafana/loki:3.5.3`, `grafana/grafana:12.1.0` (optional profile), toy services built from `python:3.12-slim`. If a pinned image tag is unavailable at execution time, bump to the nearest available same-major tag and record the change in the phase report (not a limitation — an environment note).

> **Note on mypy 2.x:** mypy jumped to 2.x since the 1.x line the executor may know. Phase 0 includes a task to confirm the strict-ish config works under 2.3.1 and adjust flags if a flag was renamed; any flag change is recorded in the phase report.

---

## 3. Repository Layout (created across phases; shown here once as the target)

```
├── pyproject.toml  uv.lock  .pre-commit-config.yaml  .gitignore  .env.example  config.yaml
├── README.md  PLAN.md  KNOWN_LIMITATIONS.md  LEARN_INDEX.md
├── deploy/
│   ├── docker-compose.yaml
│   ├── prometheus/prometheus.yml
│   ├── loki/loki-config.yaml
│   └── grafana/                       # optional profile only
├── demo_stack/
│   ├── Dockerfile
│   ├── requirements.txt               # fastapi, uvicorn, prometheus-client, psycopg[binary]
│   └── services/{common.py, orders.py, payments.py, inventory.py}
├── runbooks/                          # 8 markdown runbooks (Phase 2)
├── scripts/
│   ├── smoke_llm.py                   # dual-provider smoke test (Phase 0)
│   ├── check_protocols.py             # TODO(review)/LEARN index verifier (Phase 0)
│   └── wait_for_stack.sh
├── src/sentinel/
│   ├── config.py
│   ├── db/{models.py, session.py}     # alembic/ at repo root
│   ├── llm/{factory.py, structured.py}
│   ├── prompts/{triage.py, hypothesize.py, remediate.py, report.py}
│   ├── agent/{state.py, schemas.py, events.py, graph.py, nodes/*.py}
│   ├── rag/{embeddings.py, ingest.py, retrieve.py}
│   ├── tools/{loki.py, prometheus.py, executor.py}
│   ├── api/{app.py, deps.py, routes_alerts.py, routes_incidents.py, routes_stream.py}
│   ├── evals/{dataset.py, harness.py, scoring.py}
│   └── cli/{main.py, demo.py}
├── alembic/  alembic.ini
├── evals/dataset/*.yaml               # ≥8 incidents with known root causes
└── tests/{unit/, integration/, e2e/, fixtures/llm/}
```

---

## 3.5 Working Protocol — Quality & Workflow Clauses (binding on all phases)

The Working Protocol section that Phase 0 writes into `PLAN.md` must contain the full Learning Comments Protocol and Deferred-Work Tracking Protocol from the project brief **verbatim, plus the following clauses verbatim**: quality clauses QS-1 … QS-6 and git-workflow clauses GW-1 … GW-4. Every task-level `LEARN:` line in this plan is an explicit instruction governed by the QS clauses; every phase acceptance gate enforces both sets.

### LEARN quality clauses

- **QS-1 — Full 5-field format, always.** Every LEARN comment uses the exact block from the brief: `# LEARN[NN]: <title>` followed by `Why this way:` / `Good sides:` / `Drawbacks:` / `Concept:` / `See also:` (See also optional, everything else mandatory). A LEARN comment missing a field is a protocol violation. `scripts/check_protocols.py` lints this mechanically: it parses every `LEARN[NN]` block and fails if any of the four mandatory fields is absent.
- **QS-2 — Concept depth and audience.** The `Concept:` field must teach the underlying idea _thoroughly_ — what the concept is, why it exists, how this implementation uses it, and what breaks if you change it. Assume the reader is a competent Java/Spring engineer who is new to this Python/AI concept: anchor to familiar analogies where one exists (e.g. checkpointer ≈ workflow-engine persistence, `interrupt` ≈ a wait state / human task in jBPM, SSE ≈ a one-way `SseEmitter`), but never let the analogy replace the actual explanation.
- **QS-3 — The restate test.** A LEARN comment must teach something that is **not inferable from reading the code itself** — the rejected alternatives, the trade-off, the failure modes, the mental model. A comment that merely narrates what the adjacent code does fails. **A LEARN comment under ~6 lines of content fails the restate test by default**, unless the phase report explicitly justifies the brevity (e.g. a pure cross-reference stub per QS-4). If a phase's LEARN comments _systematically_ restate the code, the phase is **failed as a protocol violation** — this is a compliance judgment, not a taste judgment.
- **QS-4 — Cross-reference rule.** Before writing a LEARN comment, check the concept tags in `LEARN_INDEX.md`. If the concept is already explained elsewhere, write `# See also: LEARN[NN]` and add **only what is new at this location** — a short cross-reference stub is the one legitimate exception to the ~6-line floor, and must be labeled as such. Duplicating an explanation that already exists in another LEARN comment is a protocol violation.
- **QS-5 — Task-level LEARN instructions.** Wherever this plan has a `LEARN:` line, the executor must produce at least one LEARN comment on that topic, at the decision point in the code, satisfying QS-1…QS-4. Topics marked _(mandatory placement, deep-dive)_ are the canonical first explanation of that concept and must be the most thorough treatment of it in the codebase; all later occurrences of the same concept cross-reference them per QS-4.
- **QS-6 — Phase-report evidence.** Every phase-end report must **quote one LEARN comment from that phase in full** (the executor picks the one it considers strongest) and include a short self-assessment of that quote against the restate test: what does it teach that the code does not show? If any LEARN comment in the phase is under the ~6-line floor, the report must justify each such case individually.

### Git workflow clauses

- **GW-1 — Commit cadence.** The executor commits after **every completed task** with the message format `phase-N.M: <task title>` (exact, lowercase `phase-`; e.g. `phase-0.4: LLM provider factory + structured-output helper`). A commit contains work for its task only. `LEARN_INDEX.md` / `KNOWN_LIMITATIONS.md` updates ride in the same commit as the LEARN comment / `TODO(review)` marker they describe, as the protocols already require.
- **GW-2 — Phase tags.** When a phase's acceptance gate has passed, the executor tags the final commit of the phase `phase-N-complete` (annotated tag, message = phase title). The tag is created only _after_ the gate passes — a tag on a red phase is a protocol violation.
- **GW-3 — Clean boundary.** No uncommitted changes may exist at a phase boundary: `git status --porcelain` must be empty before the gate is declared passed, and the phase report includes that command's (empty) output. Untracked-but-intended files are committed; everything else is covered by `.gitignore`.
- **GW-4 — Report evidence & hook enforcement.** Every phase report lists all commit hashes created that phase (one line each: short hash + message) plus the phase tag. The pre-commit hook running `scripts/check_protocols.py` (Task 0.6) is **load-bearing**: it is what makes the LEARN and `TODO(review)` protocols fire on every commit rather than being remembered. If the hook is not installed or is bypassed (`--no-verify`), the phase is failed. The phase report attests the hook ran on every commit that phase.

---

## 4. Phase 0 — Repo Scaffold & Tooling

**Goal:** executable skeleton, both protocols bootstrapped, dual-provider LLM smoke test green, git discipline established.
**Depends on:** nothing. **Parallelizable within phase:** 0.4/0.5/0.6 after 0.1.

### Task 0.1 — Git repo + uv project skeleton

- **Files:** `pyproject.toml`, `.gitignore`, `src/sentinel/__init__.py`, `config.yaml`, `uv.lock`
- **Does:**
  1. Create the project at the WSL2-native location: `mkdir -p ~/dev2/Sentinel && cd ~/dev2/Sentinel` — never under `/mnt/c`.
  2. `git init -b main`. Set `git config core.autocrlf false` and `git config core.filemode true` locally for this repo (both are Linux defaults; setting them explicitly documents intent and protects against a Windows-global git config leaking in via a shared `%USERPROFILE%\.gitconfig`).
  3. Write `.gitignore` covering at minimum: `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `.uv-cache/` (plus any project-local uv cache dir), `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `.cache/` (sentence-transformers model cache), `*.egg-info/`, `dist/`.
  4. `uv init --package`, set `requires-python = ">=3.12"`, add all deps from §2, configure `[project.scripts] sentinel = "sentinel.cli.main:app"` (placeholder module with a no-op typer app is fine for now).
  5. Initial commit of the skeleton: `git add -A && git commit -m "phase-0.1: git repo + uv project skeleton"`.
- **Verify:** `uv sync && uv run python -c "import sentinel; print('ok')"`; `uv pip check`; `git log --oneline` shows the initial commit; `git status --porcelain` is empty; `pwd` resolves under `/home/` (not `/mnt/c`).
- **Acceptance:** `uv sync` reproducible from committed `uv.lock`; `uv pip check` reports no incompatibilities; repo initialized with a clean tree and one commit; `.gitignore` verifiably excludes `.env` (test: `touch .env && git status --porcelain` shows nothing, then remove the file).
- **LEARN:** **two mandatory comments here** (placed as header comment blocks — (a) at the top of `pyproject.toml`, (b) at the top of `.gitignore`; both are greppable per the protocol).
  (a) uv + `pyproject.toml` for a Maven/Gradle engineer (lockfile ≈ dependency-locking, `uv run` ≈ wrapper, why no hand-managed virtualenv). Full 5-field format per QS-1; `Concept:` teaches the Python packaging model (pyproject vs setup.py vs requirements.txt, why lockfiles matter) thoroughly for a Java/Spring reader; restate test per QS-3.
  (b) _(mandatory placement, deep-dive — D17)_ why the repo lives on the WSL2 native filesystem: `/mnt/c` is served via the 9P file protocol, so every file I/O syscall crosses the VM boundary — uv sync, pytest collection, and ruff do thousands of small file ops, and the overhead is multiplicative, not additive. The Windows↔WSL2 boundary also brings CRLF translation (a Windows-side `core.autocrlf=true` rewriting files the Linux side expects as LF — breaking shell scripts and pre-commit hooks) and executable-bit loss (NTFS has no POSIX mode bits, so scripts and hooks silently lose +x). `Concept:` teaches 9P mounting, NTFS-vs-ext4 semantics, and git's `core.autocrlf`/`core.filemode` settings for a Windows-only engineer; `Drawbacks:` honestly notes the repo is invisible to Windows-native tools that don't speak WSL paths and lives inside the WSL disk image; restate test per QS-3.

### Task 0.2 — Lint/type/pre-commit

- **Files:** `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]` incl. `asyncio_mode = "auto"`), `.pre-commit-config.yaml`
- **Does:** Ruff (line-length 100, `select = ["E","F","I","UP","B","ASYNC"]`), mypy strict-ish (`strict = true` with per-module relaxations only for `tests.*` and `demo_stack.*` if needed), pre-commit hooks: ruff, ruff-format, mypy, plus the local protocol hook from Task 0.6. Install hooks: `uv run pre-commit install`.
- **Verify:** `uv run pre-commit run --all-files`, then commit per GW-1 (`phase-0.2: lint/type/pre-commit`).
- **Acceptance:** all hooks pass on the skeleton; if a mypy 2.x flag differs from 1.x expectations, adjust config and note it in the phase report. The commit created in this task proves the hook chain fires on a real commit.

### Task 0.3 — Config system (D14)

- **Files:** `src/sentinel/config.py`, `config.yaml`, `.env.example`, `tests/unit/test_config.py`
- **Does:** Pydantic-settings `Settings` model: `llm.{provider, model, base_url, api_key_env, temperature}`, `embeddings.{model_name}` (fixed `all-MiniLM-L6-v2`), `database.url`, `loki.url`, `prometheus.url`, `remediation.{allowed_actions, allowed_services, dry_run, confidence_threshold}`, `verification.{delay_seconds, attempts}`. `config.yaml` ships defaults; env vars prefixed `SENTINEL_` override; `LLM_PROVIDER` maps onto `llm.provider`.
- **Verify:** `uv run pytest tests/unit/test_config.py -q`; commit per GW-1 (`phase-0.3: config system`).
- **Acceptance:** switching `LLM_PROVIDER=ollama` vs `openai` changes the resolved settings with zero code changes; `.env.example` documents every env var and contains no secrets.
- **LEARN:** config layering (pydantic-settings) for a Spring engineer — analogy to `application.yml` + `@ConfigurationProperties` + relaxed binding, and where the analogy breaks. Full 5-field format per QS-1; `Concept:` teaches the twelve-factor-style precedence chain (defaults < yaml < env) and why immutable typed settings objects beat scattered `os.getenv` calls; restate test per QS-3.

### Task 0.4 — LLM provider factory + structured-output helper (D1, D3)

- **Files:** `src/sentinel/llm/factory.py`, `src/sentinel/llm/structured.py`, `tests/unit/test_structured.py`
- **Does:** `get_chat_model(settings) -> ChatOpenAI` (base_url/api_key/model/temperature from settings; dummy key accepted for Ollama). `structured_call(model, prompt, schema: type[BaseModel])` implements the uniform JSON path: instruct with an explicit JSON schema block, extract the first balanced `{...}` (strip code fences), validate with Pydantic, on failure re-prompt with the validation error appended (repair), max 2 retries then raise `StructuredOutputError`.
- **Verify:** `uv run pytest tests/unit/test_structured.py -q`; commit per GW-1 (`phase-0.4: LLM provider factory + structured-output helper`).
- **Acceptance:** unit tests cover: clean JSON, fenced JSON, JSON with surrounding prose, repaired-after-one-retry, hard failure after 2 retries. Retry budget is exactly 2, configurable only via constant.
- **LEARN:** **two mandatory comments here.** (a) _(mandatory placement, deep-dive — D1)_: the retry/repair structured-output design — why one uniform JSON+validate+repair path beats `with_structured_output`/function-calling when a 7B local model must be supported; the full 5-field format per QS-1; `Concept:` teaches structured-output strategies generally (grammar-constrained decoding, tool-calling, prompt-and-parse) and why prompt-and-parse-with-repair is the weakest-link-proof choice; this is the canonical explanation — later prompts/nodes cross-reference it per QS-4. (b) _(mandatory placement — D3)_: why the `langchain-openai` client serves both cloud and Ollama (OpenAI-compatible API surface), 5-field format, restate test per QS-3.

### Task 0.5 — Dual-provider smoke test

- **Files:** `scripts/smoke_llm.py`, README stub section
- **Does:** Script runs the same `structured_call` against the configured provider and asserts a valid Pydantic object comes back; `--provider openai|ollama` flag overrides env. README documents: cloud path (`OPENAI_API_KEY` set) and local path (install Ollama, `OLLAMA_HOST=0.0.0.0 ollama serve`, `ollama pull qwen2.5:7b-instruct`).
- **Verify:** `uv run python scripts/smoke_llm.py --provider ollama` and, when a key is available, `--provider openai`. Without a cloud key, the openai run may be recorded as "not executed" in the phase report (environment note, not a limitation). Commit per GW-1 (`phase-0.5: dual-provider smoke test`).
- **Acceptance:** ollama path green on the execution machine; script exits non-zero with a clear message when the endpoint is unreachable.
- **LEARN:** _(mandatory placement — D4)_ `host.docker.internal` vs `localhost` from containers on Docker Desktop/WSL2. Full 5-field format per QS-1; `Concept:` teaches Docker networking namespaces (why `localhost` differs per container, what `host-gateway` does, why WSL2 makes this non-obvious); restate test per QS-3.

### Task 0.6 — Protocol bootstrap: PLAN.md, KNOWN_LIMITATIONS.md, LEARN_INDEX.md, checker

- **Files:** `PLAN.md`, `KNOWN_LIMITATIONS.md`, `LEARN_INDEX.md`, `scripts/check_protocols.py`, `.pre-commit-config.yaml` (add local hook), `README.md` (stub with limitations section)
- **Does:**
  - `PLAN.md`: copy of this plan plus a **Working Protocol** section containing the full Learning Comments Protocol and Deferred-Work Tracking Protocol text from the project brief **verbatim, plus clauses QS-1…QS-6 and GW-1…GW-4 from §3.5 verbatim**.
  - `KNOWN_LIMITATIONS.md`: created with the mandated header/entry format and seeded with the **pre-declared scope cuts** (§14 below, entries L1–L6), and `TODO(review)` markers placed where applicable (L1 in `demo_stack` once it exists — until then the entry states "Where partial coverage lives: none (component not yet created)").
  - `LEARN_INDEX.md`: numbered table (number, title, file:line, concept tag); starts with the LEARN comments added in 0.1–0.5, numbering begins at `LEARN[01]`.
  - `scripts/check_protocols.py`: verifies (a) `grep`-count of `TODO(review)` in `*.py`/`*.yaml` == number of entries in `KNOWN_LIMITATIONS.md` (deterministic rule: **every entry must have exactly one marker**; pre-declared entries whose component does not exist yet must carry their marker in `KNOWN_LIMITATIONS.md` itself on the entry's location line, which the checker counts as satisfied-until-created); (b) every `LEARN[NN]` in code has a row in `LEARN_INDEX.md` and vice versa; (c) LEARN numbers gapless; (d) **QS-1 structural lint**: every `LEARN[NN]` block contains all four mandatory fields (`Why this way:`, `Good sides:`, `Drawbacks:`, `Concept:`). Exits non-zero on any mismatch. Wired as a pre-commit `local` hook (`language: system`, `entry: uv run python scripts/check_protocols.py`, `always_run: true`, `pass_filenames: false`).
- **Verify:** `uv run python scripts/check_protocols.py && grep -rn "TODO(review)" --include="*.py" --include="*.yaml" . | wc -l`; commit per GW-1 (`phase-0.6: protocol bootstrap`).
- **Acceptance:** checker green; pre-commit blocks a commit that breaks either protocol (demonstrate by temporarily adding an untracked marker and observing the commit fail, then reverting; demonstrate a LEARN block missing `Drawbacks:` fails the lint, then revert). Both demonstrations are attested in the phase report (GW-4: the hook is load-bearing).

### Task 0.7 — Docker Compose skeleton

- **Files:** `deploy/docker-compose.yaml`, `scripts/wait_for_stack.sh`
- **Does:** Services defined but toy-service builds deferred to Phase 1: `postgres` (image `pgvector/pgvector:pg16`, healthcheck, volume), `prometheus`, `loki`, plus `sentinel-api` placeholder (build context `.`, target created in Phase 5 — for now the compose file lists it under profile `api` so Phase 0 can `up` only infra). `extra_hosts: ["host.docker.internal:host-gateway"]` on any service that will call Ollama. `scripts/wait_for_stack.sh` must be committed with the executable bit (`git update-index --chmod=+x scripts/wait_for_stack.sh` if needed) and LF endings.
- **Verify:** `docker compose -f deploy/docker-compose.yaml up -d postgres prometheus loki && bash scripts/wait_for_stack.sh`; commit per GW-1 (`phase-0.7: docker compose skeleton`).
- **Acceptance:** all three containers healthy; `psycopg` connects from the WSL2 host (`uv run python -c "import psycopg; psycopg.connect('<url>').execute('select 1')"`).

### Phase 0 acceptance (gate) — this gate defines the phase-report format for ALL phases

1. Tasks 0.1–0.7 acceptance all green.
2. `uv run python scripts/check_protocols.py` exits 0 — including the QS-1 5-field lint.
3. **LEARN quality audit per §3.5 (QS-1…QS-4)** performed by the executor and attested in the report.
4. Phase report contains, in this order:
   a. New LEARN comments added (numbers + titles only).
   b. **One LEARN comment from the phase quoted in full, with a self-assessment against the restate test (QS-6)** — what does it teach that the code does not show?
   c. Individual justification for any LEARN comment under the ~6-line floor (QS-3), or a statement that none exist.
   d. New limitation entries added (titles), and count-match confirmation between `TODO(review)` markers and `KNOWN_LIMITATIONS.md` entries.
   e. Environment notes (mypy flag adjustments, untested cloud path, image tag bumps).
   f. **Commit evidence (GW-4): every commit hash created this phase (short hash + message), the empty output of `git status --porcelain` (GW-3), attestation that the pre-commit hook ran on every commit, and the `phase-N-complete` tag once created.**
5. **Git gate (GW-1…GW-3):** one commit per task with the exact `phase-N.M: <task title>` format; `git status --porcelain` empty; after items 1–4 pass, `git tag -a phase-0-complete -m "Repo scaffold & tooling"`.

---

## 5. Phase 1 — Demo Target Stack

**Goal:** 3 toy services with chaos injection, scraped by Prometheus, logging to Loki, writing deploy events.
**Depends on:** Phase 0. **Parallelizable with:** Phase 2 (different files, shared only the compose file — sequence compose edits, parallelize the rest; commits are serialized in task order so GW-1's one-task-per-commit format stays intact).

### Task 1.1 — Toy service shared code

- **Files:** `demo_stack/services/common.py`, `demo_stack/requirements.txt` (`fastapi==0.141.1`, `uvicorn==0.52.4`, `prometheus-client` latest-0.x pinned at execution time, `psycopg[binary]==3.3.4`)
- **Does:** A factory `create_app(service_name)` producing a FastAPI app with: `/healthz`, `/work` (simulated request emitting latency histogram + request/5xx counters + structured JSON log line), `/chaos` POST accepting `{type: latency_spike|error_burst|memory_leak|bad_deploy, duration_seconds?}`, `/metrics` (prometheus-client), and a deploy-event writer that inserts `{service, version, event, created_at}` into `deployments` via psycopg on startup and on `bad_deploy`. Chaos state held in a module-level object with a reset timer.
- **Verify:** build and run one service locally: `docker build -t sentinel-toy demo_stack && docker run --rm -p 9001:8000 sentinel-toy python -m services.orders` then `curl localhost:9001/healthz`
- **Acceptance:** `/chaos {"type":"error_burst"}` makes `/work` return 500s and the `http_errors_total` counter increase; chaos auto-resets after `duration_seconds`.
- **LEARN:** two comments. (a) chaos-as-state-machine and why chaos state is deliberately process-local (acceptable here; ties to L3 single-process limitation — honest `Drawbacks:` field required). (b) prometheus-client metric types (Counter vs Histogram) for a Java/Micrometer engineer. Both: full 5-field format per QS-1; `Concept:` fields teach the underlying idea (fault injection as deterministic state machines; pull-based metrics and Micrometer analogy) rather than narrating the code; restate test per QS-3.

### Task 1.2 — Three service instances + compose wiring

- **Files:** `demo_stack/Dockerfile`, `demo_stack/services/{orders.py, payments.py, inventory.py}`, `deploy/docker-compose.yaml`
- **Does:** Three near-identical entrypoints differing only in `SERVICE_NAME`/`PORT`. Compose services `orders`, `payments`, `inventory` on the shared network with env `DATABASE_URL` pointing at the compose Postgres.
- **Verify:** `docker compose -f deploy/docker-compose.yaml up -d --build && for p in 9001 9002 9003; do curl -sf localhost:$p/healthz; done`
- **Acceptance:** all three healthy; each writes a deploy row on boot (`psql ... -c 'select service, event from deployments'` shows ≥3 rows — note: `deployments` table arrives in Phase 2; if Phase 1 runs before Phase 2, services must create the table idempotently at boot with `CREATE TABLE IF NOT EXISTS`, and Phase 2's alembic migration must reconcile. **Decision:** services create-if-not-exists in Phase 1; Phase 2 migration adopts the existing table without altering it).
- **LEARN:** _(mandatory placement — D8)_ why demo services write deploy events directly to the DB instead of via an ingestion API. Full 5-field format per QS-1; `Concept:` teaches the shared-database integration pattern and its coupling cost (the honest `Drawbacks:` field is the point here — what breaks when two components own one table); restate test per QS-3.

### Task 1.3 — Prometheus + Loki wiring

- **Files:** `deploy/prometheus/prometheus.yml`, `deploy/loki/loki-config.yaml`, `deploy/docker-compose.yaml`
- **Does:** Prometheus scrapes all three services every 5s (D16). Loki runs in single-binary mode; toy services push log lines directly to Loki's push API (`POST /loki/api/v1/push`) from a background thread, keeping stdout as a copy. No Promtail, no Docker logging plugin.
- **Verify:** `curl -s "localhost:9090/api/v1/query?query=up"` shows 3 targets up; inject error_burst, wait 10s, then `curl -sG localhost:3100/loki/api/v1/query_range --data-urlencode 'query={service="orders"}' ...` returns the error lines.
- **Acceptance:** a chaos burst is visible in both Prometheus (`rate(http_errors_total[1m])`) and Loki within 15s.
- **LEARN:** push-vs-pull logging and why direct push is acceptable for a demo while production would use an agent (Promtail/Alloy/Fluent Bit). Full 5-field format per QS-1; `Concept:` teaches log aggregation topologies generally; `Drawbacks:` must honestly cover at-least-once/buffering gaps of the naive push thread; restate test per QS-3. (Documented in README as a design choice — not a weakened requirement, so no `TODO(review)`.)

### Task 1.4 — Chaos determinism helper

- **Files:** `demo_stack/services/common.py` (extend), `tests/e2e/helpers.py` (new, used later)
- **Does:** Add `/chaos/status` returning active fault + remaining seconds, so tests and the demo script can poll instead of sleeping blindly.
- **Verify:** `curl localhost:9001/chaos/status` after injecting a fault.
- **Acceptance:** status reflects active fault; returns `{"active": null}` after reset.

### Phase 1 acceptance (gate)

1. Full `docker compose up -d --build` brings up postgres+prometheus+loki+3 services healthy.
2. Each chaos type on `orders` is observable in Prometheus and Loki.
3. `bad_deploy` inserts a `deployments` row with the new version.
4. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f, including the quoted LEARN comment with restate-test self-assessment and the commit evidence). Expected new limitations: none beyond pre-declared — any discovered one is logged per protocol or the phase fails.
5. Git gate per GW-1…GW-3: commits `phase-1.1`…`phase-1.4` in the exact format, clean tree, then `git tag -a phase-1-complete -m "Demo target stack"`.

---

## 6. Phase 2 — Data Layer

**Goal:** schema, pgvector, runbook corpus, ingestion.
**Depends on:** Phase 0. **Parallelizable with:** Phase 1.

### Task 2.1 — Alembic setup + app schema (D7)

- **Files:** `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`, `src/sentinel/db/models.py`, `src/sentinel/db/session.py`
- **Does:** Tables:
  - `incidents(id uuid pk, alert_name text, service text, severity text, status text, raw_alert jsonb, created_at, updated_at)` — status ∈ `investigating|awaiting_approval|remediating|verifying|resolved|escalated|rejected`
  - `deployments(id bigserial pk, service text, version text, event text, created_at)` — adopt the Phase 1 create-if-not-exists table (migration asserts columns exist, does not recreate)
  - `agent_events(id bigserial pk, incident_id uuid fk, node text, event_type text, payload jsonb, created_at)`
  - `runbooks(id bigserial pk, title text, content text, embedding vector(384))` — pgvector, dim 384 fixed by D2
    Migration enables `CREATE EXTENSION IF NOT EXISTS vector`.
- **Verify:** `docker compose -f deploy/docker-compose.yaml up -d postgres && uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head`
- **Acceptance:** round-trip migration clean; `\d runbooks` shows `vector(384)`; models.py mirrors the schema and passes mypy.
- **LEARN:** _(mandatory placement — D7)_ Alembic for a Flyway/Liquibase user: why handwritten migrations here instead of autogenerate, how `upgrade`/`downgrade` map to migrate/undo. Full 5-field format per QS-1; `Concept:` teaches schema-migration philosophy (versioned, ordered, reversible) and what adopting a pre-existing table (the Phase 1 `deployments` table) teaches about migration baselining; restate test per QS-3.

### Task 2.2 — Runbook corpus

- **Files:** `runbooks/*.md` — 8 files: `latency-spike-downstream.md`, `error-burst-after-deploy.md`, `memory-leak-slow-growth.md`, `bad-deploy-rollback.md`, `connection-pool-exhaustion.md`, `disk-pressure.md`, `noisy-neighbor-cpu.md`, `generic-triage-first-steps.md`
- **Does:** Each runbook 150–400 words: symptoms (metric/log signatures matching what the chaos types actually produce), likely causes, diagnostic steps, remediation options using only whitelisted action names. Written to be retrievable: embed the exact metric names (`http_errors_total`, `http_request_duration_seconds`, `process_resident_memory_bytes`) the agent will see.
- **Verify:** `ls runbooks/*.md | wc -l` → 8; manual skim checklist in phase report.
- **Acceptance:** every chaos type has ≥1 runbook naming its observable signatures; no runbook references actions outside the whitelist.

### Task 2.3 — Embedding + ingestion (D2)

- **Files:** `src/sentinel/rag/embeddings.py`, `src/sentinel/rag/ingest.py`, `tests/unit/test_ingest.py`
- **Does:** `embeddings.py` lazily loads `SentenceTransformer("all-MiniLM-L6-v2")` (model cached in a `.cache/` dir, path configurable; first download may happen at ingest time — documented in README). `ingest.py` CLI (`uv run sentinel ingest-runbooks`) chunks each runbook (whole doc + per-section chunks, simple splitter), embeds, upserts into `runbooks`.
- **Verify:** `uv run sentinel ingest-runbooks && psql ... -c 'select count(*) from runbooks'` (expect ≥ 8 rows)
- **Acceptance:** re-running ingestion is idempotent (upsert by content hash); unit test covers chunking + upsert logic with the model mocked.
- **LEARN:** _(mandatory placement, deep-dive — D2)_ why embeddings are provider-independent local models, and vector search fundamentals. Full 5-field format per QS-1; `Concept:` teaches embeddings and cosine similarity from first principles for a relational-DB engineer — what `vector(384)` actually stores, why the same model must embed corpus and query, why switching embedding providers would silently invalidate the stored vectors (this is the real reason for D2 — the code alone never shows it; that is the restate test, QS-3).

### Task 2.4 — Retrieval

- **Files:** `src/sentinel/rag/retrieve.py`, `tests/unit/test_retrieve.py`
- **Does:** `retrieve_runbooks(query: str, k: int = 3)` embedding the query and selecting by cosine distance (`embedding <=> %s`) via pgvector's psycopg integration. Returns Pydantic `RunbookHit(title, snippet, score)`.
- **Verify:** integration check in `tests/integration/test_rag_pg.py` (marked `integration`, requires compose postgres): ingest a 2-doc fixture, retrieve, assert the right doc wins.
- **Acceptance:** integration test green; k and a minimum-score floor come from config.
- **LEARN:** per the cross-reference rule (QS-4): `See also:` the ingestion LEARN from Task 2.3, adding only what retrieval adds — query-time embedding symmetry and the score-floor trade-off (too low = noise in the context window, too high = empty context). If this adds < 6 lines, it is a labeled cross-reference stub, justified in the phase report per QS-3.

### Phase 2 acceptance (gate)

1. Migrations round-trip; pgvector extension live; 8 runbooks ingested.
2. Retrieval returns the chaos-matching runbook for a hand-written query per chaos type (assert in `tests/integration/test_rag_pg.py` with real embeddings — small model, acceptable test time).
3. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
4. Git gate per GW-1…GW-3: commits `phase-2.1`…`phase-2.4` in the exact format, clean tree, then `git tag -a phase-2-complete -m "Data layer"`.

---

## 7. Phase 3 — Agent Core

**Goal:** full LangGraph graph with mocked-LLM unit tests per node, checkpointed, interrupt/resume working.
**Depends on:** Phases 0, 2 (schema). Tools (Phase 4) are consumed behind interfaces — Phase 3 uses fakes, so **3 and 4 are parallelizable** if the tool interfaces (`tools/loki.py` etc. function signatures) are stubbed first in Phase 3's Task 3.1.

### Task 3.1 — State + schemas + tool interfaces

- **Files:** `src/sentinel/agent/state.py`, `src/sentinel/agent/schemas.py`, `src/sentinel/agent/events.py`, `src/sentinel/tools/{loki.py, prometheus.py, executor.py}` (signatures + `NotImplementedError` bodies if Phase 4 hasn't landed)
- **Does:** `AgentState` TypedDict (LangGraph state): `incident_id, alert, triage: TriageResult|None, logs: list[LogExcerpt], metrics: list[MetricFinding], deploys: list[DeployEvent], runbooks: list[RunbookHit], hypothesis: RootCauseHypothesis|None, remediation: RemediationProposal|None, approval: bool|None, execution: ExecutionResult|None, verification: VerificationResult|None, report: IncidentReport|None, errors: list[str]`. All structured payloads are Pydantic models in `schemas.py` — notably `RootCauseHypothesis(cause, confidence: float, evidence: list[str], affected_service, references: list[str])` and `RemediationProposal(action, target_service, params, rationale)`. `events.py`: the asyncio pub/sub bus + `emit(incident_id, node, event_type, payload)` that persists to `agent_events` and publishes to subscribers (D10).
- **Verify:** `uv run pytest tests/unit/test_state.py -q` + `uv run mypy src/sentinel/agent`
- **Acceptance:** state is mypy-clean; every Pydantic model has `model_config = ConfigDict(extra="forbid")` to catch model hallucination drift.
- **LEARN:** two comments. (a) LangGraph state model (TypedDict + reducers) vs a Spring workflow engine's context object — full 5-field format per QS-1, `Concept:` teaches graph-state reduction (how partial node updates merge) thoroughly. (b) why `extra="forbid"` matters when LLMs invent keys — `Concept:` teaches Pydantic validation strictness as a contract boundary against hallucination; the code shows the one-liner, the comment must explain the failure mode it prevents (restate test, QS-3).

### Task 3.2 — Prompts module

- **Files:** `src/sentinel/prompts/{triage.py, hypothesize.py, remediate.py, report.py}`
- **Does:** Versioned prompt constants (`PROMPT_VERSION = "1"` per module) with: role, task, explicit JSON schema block mirroring the Pydantic model, one worked few-shot example, and a "respond with JSON only" instruction. Design-choice comments per prompt.
- **Verify:** `uv run pytest tests/unit/test_prompts.py -q` (asserts schema block keys match the Pydantic model fields — a cheap drift guard)
- **Acceptance:** drift-guard test green for all four prompts.
- **LEARN:** prompt design for weak models: schema-in-prompt + few-shot + repair loop as defense in depth. Per QS-4, `See also:` the D1 deep-dive from Task 0.4 — this comment adds only prompt-side technique (why few-shot examples stabilize small models, why the schema block mirrors the Pydantic model exactly, prompt versioning discipline). 5-field format per QS-1; if short, labeled cross-reference stub justified in the phase report per QS-3.

### Task 3.3 — Nodes with mocked-LLM tests

- **Files:** `src/sentinel/agent/nodes/{triage.py, gather_logs.py, gather_metrics.py, gather_deploys.py, runbook_rag.py, hypothesize.py, remediate.py, human_gate.py, execute.py, verify.py, report.py}`, `tests/unit/nodes/test_*.py` (one per node), `tests/fixtures/llm/*.json`
- **Does:** Each node is a plain async function `(state, config) -> dict` (partial state update). LLM-backed nodes (triage, hypothesize, remediate, report) call `structured_call` with the model injected via `config["configurable"]["llm"]` so tests pass a fake. Gather nodes call the tool interfaces. `remediate` enforces: action ∈ whitelist AND confidence ≥ threshold, else forces `no_action` + escalate flag. `human_gate` calls `interrupt({...proposal...})`. `execute` calls the executor (dry-run aware). `verify` re-queries Prometheus per D15. `report` builds `IncidentReport` and persists it.
- **Verify:** `uv run pytest tests/unit/nodes -q`
- **Acceptance:** every node has ≥2 tests (happy path + one edge: empty tool result / low confidence / non-whitelisted action / rejected approval). LLM fakes are recorded JSON fixtures, not inline mocks, so evals reuse them.
- **LEARN:** two comments. (a) dependency injection via LangGraph `config["configurable"]` vs constructor injection (Spring analogy) — 5-field format per QS-1, `Concept:` teaches why graph nodes can't receive constructor args and what testability costs/buys here. (b) _(mandatory placement — D6, part 1 of 2)_ `interrupt()` semantics at the node level: what executing `interrupt()` actually does (raises through the graph, persists state at the boundary, surfaces a payload), why the node contains no waiting loop. `Concept:` teaches cooperative suspension vs blocking waits for a threads-and-`@Async` engineer; restate test per QS-3. The polling-vs-interrupt comparison itself lives in Task 3.4's deep-dive; cross-reference it per QS-4 rather than duplicating.

### Task 3.4 — Graph assembly + checkpointing (D5, D6)

- **Files:** `src/sentinel/agent/graph.py`, `tests/integration/test_graph.py`
- **Does:** Explicit `StateGraph` wiring: `triage → (investigate? gather_logs → gather_metrics → gather_deploys → runbook_rag → hypothesize → remediate → (needs_approval? human_gate → execute → verify | report) | report)` with named conditional edges, no dynamic magic. `build_graph(checkpointer)` compiles with `PostgresSaver`; `PostgresSaver.setup()` runs idempotently at API startup. Integration test runs the full graph against a **FakeLLM** (fixture-driven), real compose Postgres checkpointer, fake tools: alert → interrupt fires at `human_gate`; resume with `Command(resume={"approved": True})`; assert `report` node reached and `agent_events` rows exist.
- **Verify:** `docker compose -f deploy/docker-compose.yaml up -d postgres && uv run pytest tests/integration/test_graph.py -q`
- **Acceptance:** interrupt/resume round-trips through a real Postgres checkpointer; killing and recreating the graph object between interrupt and resume (simulated restart) still resumes correctly — asserted in the test.
- **LEARN:** **two mandatory deep-dive comments here.** (a) _(mandatory placement, deep-dive — D5)_ Postgres checkpointer vs in-memory: what a checkpoint actually contains (state snapshot + pending interrupt), why `thread_id` must be the stable incident id, what `PostgresSaver.setup()` creates, what would silently break with an in-memory saver (restart = orphaned approvals). (b) _(mandatory placement, deep-dive — D6)_ LangGraph `interrupt`/`Command(resume=...)` vs polling: why resumable-graph suspension beats an API polling loop (durability, single-writer semantics, no state machine re-implementation); `Concept:` compares to BPMN human-task/wait-state for the Java reader. Both: full 5-field format per QS-1, thorough `Concept:` fields, restate test per QS-3 — these are the canonical explanations; the API layer (Phase 5) cross-references them per QS-4.

### Phase 3 acceptance (gate)

1. All node unit tests + graph integration test green.
2. Graph survives process-restart-simulation mid-run.
3. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
4. Git gate per GW-1…GW-3: commits `phase-3.1`…`phase-3.4` in the exact format, clean tree, then `git tag -a phase-3-complete -m "Agent core"`.

---

## 8. Phase 4 — Tools

**Goal:** real Loki/Prometheus clients and the Docker executor.
**Depends on:** Phase 0, Phase 1 (live targets to test against). **Parallelizable with:** Phase 3.

### Task 4.1 — Loki client (D9)

- **Files:** `src/sentinel/tools/loki.py`, `tests/integration/test_loki_tool.py`
- **Does:** `query_logs(service: str, since: timedelta, limit: int = 100) -> list[LogExcerpt]` via `GET /loki/api/v1/query_range` with a fixed LogQL selector `{service="<name>"} |~ "(?i)error|warn|exception"`; `httpx` client with 5s timeout and tenacity retry (3 attempts, exponential backoff, retry only on connect/5xx).
- **Verify:** with stack up and an `error_burst` injected: `uv run pytest tests/integration/test_loki_tool.py -q`
- **Acceptance:** returns the injected error lines; retries are unit-tested with a stub transport (2 failures then success).
- **LEARN:** retry policy design (why 3 attempts + exponential backoff + selective retryable errors, why never retry 4xx). Full 5-field format per QS-1; `Concept:` teaches transient-vs-permanent failure classification for someone used to Spring Retry; one comment here covers both 4.1 and 4.2 — Task 4.2 cross-references it per QS-4.

### Task 4.2 — Prometheus client (D9)

- **Files:** `src/sentinel/tools/prometheus.py`, `tests/integration/test_prometheus_tool.py`
- **Does:** `query_anomalies(service, window) -> list[MetricFinding]` running a small fixed PromQL suite: error rate `rate(http_errors_total{service=...}[2m])`, p95 latency from the histogram, resident memory delta; each finding carries the expression, values, and a simple threshold breach flag. `instant_query(expr)` helper reused by `verify` node (D15).
- **Verify:** `uv run pytest tests/integration/test_prometheus_tool.py -q` with an active chaos fault.
- **Acceptance:** each chaos type produces a breach on its corresponding expression; timeouts and empty results handled (empty result is a finding with `breach=False`, never an exception).
- **LEARN:** per QS-4, cross-reference the Task 4.1 retry LEARN (`See also:`); add only the PromQL-specific teaching here: `rate()` over counters, histogram quantiles, and why an empty query result is data (absence of signal), not an error. 5-field format per QS-1; restate test per QS-3.

### Task 4.3 — Docker executor with whitelist + dry-run (D11)

- **Files:** `src/sentinel/tools/executor.py`, `tests/unit/test_executor.py`, `tests/integration/test_executor.py`
- **Does:** `execute(action, target_service, params, dry_run) -> ExecutionResult`. Whitelist enforced twice: action ∈ `settings.remediation.allowed_actions` and target ∈ `allowed_services` (defense in depth — raise `RemediationNotAllowed` otherwise). Actions: `restart_service` (`container.restart()`), `rollback_deploy` (restarts container with the previous image tag recorded in `deployments`; if no previous tag → escalate result), `scale_replicas` (compose-v1 limitation: implemented as `docker update` restart of N named replica containers if present, else returns `not_applicable` — **pre-declared limitation L7**, see §14), `no_action` (no-op). `dry_run=True` logs the exact intended call and returns `ExecutionResult(dry_run=True, ...)`.
- **Verify:** `uv run pytest tests/unit/test_executor.py -q` (mocked docker client) and, with stack up, `uv run pytest tests/integration/test_executor.py -q` restarting `orders` for real.
- **Acceptance:** non-whitelisted action/service raises before any docker call; dry-run makes zero docker SDK mutation calls (asserted via mock); real restart integration test green. The API container mounts `/var/run/docker.sock` (compose change in Phase 5).
- **LEARN:** _(mandatory placement, deep-dive)_ whitelist-as-code + config and dry-run: why the executor — not the LLM node — is the enforcement point (never trust model output at the action boundary), why dry-run is the default, and the security implications of mounting the Docker socket (root-equivalent on the host; acceptable only because L2 declares demo posture). Full 5-field format per QS-1 with an honest `Drawbacks:` field; `Concept:` teaches capability-gating of agent actions generally (the pattern: propose in the graph, authorize at the executor); restate test per QS-3.

### Phase 4 acceptance (gate)

1. All tool integration tests green against the live demo stack.
2. Executor refuses anything off-whitelist even if the agent proposes it.
3. L7 added to `KNOWN_LIMITATIONS.md` with its `TODO(review)` marker in `executor.py`; protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
4. Git gate per GW-1…GW-3: commits `phase-4.1`…`phase-4.3` in the exact format, clean tree, then `git tag -a phase-4-complete -m "Tools"`.

---

## 9. Phase 5 — API & HITL

**Goal:** FastAPI control plane: alert webhook, incident read APIs, approval endpoints, SSE, CLI.
**Depends on:** Phases 3, 4. (Phase 5 and 6 can overlap: 6 changes only `verify` node behavior already stubbed in 3.)

### Task 5.1 — App skeleton + alert webhook

- **Files:** `src/sentinel/api/{app.py, deps.py, routes_alerts.py}`, `deploy/docker-compose.yaml` (`sentinel-api` service: build context `.`, mounts `/var/run/docker.sock`, `extra_hosts` for Ollama, env from `.env`), `Dockerfile` (repo root, `python:3.12-slim` + `uv sync`)
- **Does:** `POST /alerts/webhook` accepts an Alertmanager v4 payload, maps the first alert to an `Incident` row (status `investigating`), and launches the graph as a background `asyncio` task with `thread_id = incident.id` and the real LLM/tools. Startup: run `alembic upgrade head` (subprocess) + `PostgresSaver.setup()`.
- **Verify:** `docker compose -f deploy/docker-compose.yaml up -d --build sentinel-api` then `curl -X POST localhost:8000/alerts/webhook -d @tests/fixtures/alertmanager_error_burst.json` and `curl localhost:8000/incidents`
- **Acceptance:** webhook returns `202` + incident id; a graph run starts; duplicate alertname+service within 60s dedupes to the existing incident (idempotency).
- **LEARN:** two comments. (a) background `asyncio` task vs a task queue (Celery/Temporal): why a fire-and-forget task is right for a single-process demo and exactly which guarantees it lacks (no retry on crash mid-run before first checkpoint, no distribution). (b) the Alertmanager webhook payload shape and the dedupe choice for someone who's never seen alert grouping. Both: 5-field format per QS-1, honest `Drawbacks:`, restate test per QS-3.

### Task 5.2 — Incident read APIs

- **Files:** `src/sentinel/api/routes_incidents.py`, `tests/unit/test_api_incidents.py`
- **Does:** `GET /incidents` (list, status filter, pagination) and `GET /incidents/{id}` returning the incident row plus the full ordered `agent_events` trace plus current LangGraph state summary (from the checkpointer).
- **Verify:** `uv run pytest tests/unit/test_api_incidents.py -q` (httpx ASGI transport, DB faked) and live `curl` against compose.
- **Acceptance:** trace endpoint reflects every emitted event in order; unknown id → 404 problem+json.

### Task 5.3 — Approval endpoints (D6)

- **Files:** `src/sentinel/api/routes_incidents.py` (extend), `tests/integration/test_approval_flow.py`
- **Does:** `POST /incidents/{id}/approve` / `/reject` resume the interrupted graph with `Command(resume={"approved": true|false})` in a background task; reject routes the graph to `report` with status `rejected`. Guard: 409 if the incident is not in `awaiting_approval`.
- **Verify:** `uv run pytest tests/integration/test_approval_flow.py -q` (compose postgres, FakeLLM) — alert → wait for `awaiting_approval` → approve → assert `execute` ran (executor in dry-run for the test) and status becomes `verifying`.
- **Acceptance:** approval of a non-pending incident → 409; the full approve path works through HTTP, not just direct graph calls.
- **LEARN:** per QS-4, `See also:` the D6 deep-dive in Task 3.4 — this comment adds only the API-side concerns: why resume happens through the checkpointer rather than in-memory graph handles, why the 409 guard maps to the interrupt state, and what happens if two approvals race (last-writer / checkpoint conflict behavior). 5-field format per QS-1; labeled cross-reference stub justified in the phase report if under the floor (QS-3).

### Task 5.4 — SSE streaming (D10)

- **Files:** `src/sentinel/api/routes_stream.py`
- **Does:** `GET /incidents/{id}/stream` (sse-starlette `EventSourceResponse`) replays persisted `agent_events` then tails live bus events until the run reaches a terminal status; heartbeat comment every 15s.
- **Verify:** `curl -N localhost:8000/incidents/<id>/stream` during a demo run shows node-by-node events.
- **Acceptance:** a client connecting mid-run sees history then live events; stream closes on terminal status; no events lost between replay and live tail (dedupe by event id).
- **LEARN:** _(mandatory placement, deep-dive — D10)_ SSE vs WebSocket: why one-way server-push over HTTP covers the demo (and what WebSocket would cost: connection lifecycle, backpressure, proxies), plus the replay-then-tail consistency problem and the id-based dedupe trick (the gap between "read history" and "subscribe live" is the bug this design exists to close — not visible in the code alone; that is the restate test, QS-3). Full 5-field format per QS-1; for the Spring reader, anchor to `SseEmitter`.

### Task 5.5 — CLI

- **Files:** `src/sentinel/cli/{main.py, demo.py}`, README demo section stub
- **Does:** typer commands: `sentinel incidents list|show <id>|approve <id>|reject <id>|watch <id>` (watch = SSE consumer rendering rich live updates), `sentinel demo` (Phase 8 wires the full scripted demo; here it triggers one chaos + webhook and tails), `sentinel ingest-runbooks` (already used in Phase 2).
- **Verify:** `uv run sentinel incidents list` against the running stack.
- **Acceptance:** a pending approval can be approved from the CLI and the stream reflects it.

### Phase 5 acceptance (gate)

1. Alert → investigate → interrupt → CLI approve → execute(dry-run false per config) → verify → report, all through the API.
2. SSE stream is complete and ordered.
3. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
4. Git gate per GW-1…GW-3: commits `phase-5.1`…`phase-5.5` in the exact format, clean tree, then `git tag -a phase-5-complete -m "API & HITL"`.

---

## 10. Phase 6 — Remediation Verification Loop

**Goal:** post-action metric re-check and auto-escalation (D15).
**Depends on:** Phase 5 (full path live). Small phase by design — the `verify` node stub from Phase 3 becomes real.

### Task 6.1 — Verification logic

- **Files:** `src/sentinel/agent/nodes/verify.py` (replace stub), `tests/unit/nodes/test_verify.py`, `tests/integration/test_verification_loop.py`
- **Does:** After `execute`, wait `verification.delay_seconds`, then evaluate the original alerting PromQL expression via `tools.prometheus.instant_query` up to `verification.attempts` times with backoff. All clear → `status=resolved`; still breaching → `status=escalated`, emit `escalation` event with the last metric values, route to `report`.
- **Verify:** unit tests (metric sequences: clear-on-first, clear-on-third, never-clear) + integration: real `error_burst` with 60s duration, approve `restart_service` (which clears the chaos state), assert `resolved`.
- **Acceptance:** a chaos fault whose duration outlives the remediation (e.g. memory_leak without restart) produces `escalated`; delay/attempts come from config, not constants.
- **LEARN:** why fixed-window re-checks instead of continuous watch: simplicity vs flap risk, and what a production version would do (sustained-recovery windows, error budgets). Full 5-field format per QS-1; `Drawbacks:` must name the accepted risk explicitly and point at limitation L4 (pair with L4's `TODO(review)` marker per the brief's mandatory-placement rule); restate test per QS-3.

### Task 6.2 — Negative-path integration test

- **Files:** `tests/integration/test_verification_loop.py` (extend)
- **Does:** Inject `error_burst` with duration 300s, approve a remediation that does **not** clear the fault (`scale_replicas` → `not_applicable`), assert `escalated` and the escalation event payload contains metric values.
- **Verify:** `uv run pytest tests/integration/test_verification_loop.py -q`
- **Acceptance:** escalation path exercised end-to-end with real metrics.

### Phase 6 acceptance (gate)

1. Both verification outcomes (resolved, escalated) proven with real chaos + real Prometheus.
2. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
3. Git gate per GW-1…GW-3: commits `phase-6.1`…`phase-6.2` in the exact format, clean tree, then `git tag -a phase-6-complete -m "Remediation verification loop"`.

---

## 11. Phase 7 — Evals & E2E

**Goal:** eval harness with ≥8 known-root-cause incidents; one scripted E2E per chaos type.
**Depends on:** Phases 3–6.

### Task 7.1 — Eval dataset

- **Files:** `evals/dataset/*.yaml` — 8 incidents: 2× error_burst (one deploy-correlated, one not), 2× latency_spike, 2× memory_leak, 2× bad_deploy. Each: `alert` payload, `known_cause` (category + affected_service), `expected_action`, and canned tool outputs (logs/metrics/deploys/runbooks) matching what the real tools would return.
- **Verify:** `uv run pytest tests/unit/test_eval_dataset.py -q` (schema-validates all 8 files)
- **Acceptance:** ≥ 8 valid entries covering all four chaos types.

### Task 7.2 — Harness + scoring (D13)

- **Files:** `src/sentinel/evals/{dataset.py, harness.py, scoring.py}`, `tests/unit/test_scoring.py`
- **Does:** Runs the graph per dataset entry with tools stubbed from the entry's canned outputs. Modes: `mock` (FakeLLM fixture responses — deterministic, threshold 100%) and `live` (real configured LLM, threshold ≥ 75%). Scoring: hypothesis correct iff `affected_service` matches AND cause-category matches (mapped via a small synonym table in `scoring.py`); remediation correct iff proposed action == `expected_action`. Prints a rich table: per-incident pass/fail + aggregate accuracy + pass/fail vs threshold. LangSmith: if `LANGSMITH_API_KEY` set, log runs; otherwise a logged no-op (L6).
- **Verify:** `uv run sentinel evals run --mode mock` and `--mode live` (live at least once in ollama mode; result recorded in phase report)
- **Acceptance:** mock mode 100%; live mode ≥ 75% with `qwen2.5:7b-instruct` (if the local model falls short, **prompt iteration is part of this task** — the executor improves prompts, never lowers the threshold silently; a threshold change would be a protocol-logged limitation requiring owner sign-off).
- **LEARN:** _(mandatory placement, deep-dive)_ eval design: why a deterministic mock mode exists alongside live mode (separating harness bugs from model quality), why accuracy is scored on structure (category + service + action) instead of free-text similarity, and how to read a small-N eval honestly (8 incidents is a smoke signal, not a benchmark). Full 5-field format per QS-1 with honest `Drawbacks:` (small N, synonym-table subjectivity); restate test per QS-3.

### Task 7.3 — E2E per chaos type

- **Files:** `tests/e2e/test_chaos_{latency,errors,memory,bad_deploy}.py`, `tests/e2e/helpers.py` (extend), `scripts/wait_for_stack.sh` (extend)
- **Does:** Four scripted scenarios (pytest, marked `e2e`, run against the full compose stack with `LLM_PROVIDER=ollama`): inject chaos via `/chaos` → fire webhook fixture → poll `/incidents/{id}` until `awaiting_approval` → approve via API → poll until terminal → assert status ∈ {resolved, escalated} and that a hypothesis + remediation exist. These are smoke-grade E2E: they assert the pipeline completes, not hypothesis correctness (that's the evals' job).
- **Verify:** `docker compose up -d --build && uv run pytest tests/e2e -m e2e -q`
- **Acceptance:** all four green; total runtime < 15 min; each scenario cleans up its chaos (or relies on auto-reset — verified via `/chaos/status`).

### Phase 7 acceptance (gate)

1. Eval table printed; mock 100%, live ≥ 75% (recorded in report).
2. Four E2E scenarios green.
3. Protocol check green (including QS-1 lint); **LEARN quality audit per §3.5**; phase report in the §4-gate format (items 4a–4f).
4. Git gate per GW-1…GW-3: commits `phase-7.1`…`phase-7.3` in the exact format, clean tree, then `git tag -a phase-7-complete -m "Evals & E2E"`.

---

## 12. Phase 8 — Docs & Polish

**Goal:** owner-consumable docs and a final protocol audit.
**Depends on:** all previous.

### Task 8.1 — README

- **Files:** `README.md`
- **Does:** Architecture mermaid diagram (toy services → Prometheus/Loki/Postgres ← sentinel-api agent loop → human approval → Docker executor); WSL2 + Docker Desktop setup incl. the WSL2-native repo location (work under `~/dev2`, edit via the editor's WSL remote mode — cross-ref the D17 LEARN comment), Ollama (`OLLAMA_HOST=0.0.0.0`, `ollama pull qwen2.5:7b-instruct`, note about first-run model download); quickstart (`docker compose -f deploy/docker-compose.yaml up -d --build` + `uv run sentinel demo`); demo walkthrough (what to watch: `sentinel incidents watch`); design-decision log (condensed §1 of this plan); known-limitations section linking `KNOWN_LIMITATIONS.md` with one sentence per **user-visible** entry (L1–L5, L7).
- **Verify:** render the mermaid block (markdown preview), click every command in the walkthrough once on a clean checkout (`git clone ~/dev2/Sentinel /tmp/sentinel-clean && cd /tmp/sentinel-clean` and follow the README verbatim).
- **Acceptance:** a clean-clone run of exactly the README commands reproduces the demo.

### Task 8.2 — Demo script polish

- **Files:** `src/sentinel/cli/demo.py`
- **Does:** `sentinel demo` orchestrates: health-check the stack (clear error if not up), inject `bad_deploy` on `orders`, fire the webhook, open the watch stream, pause at the approval prompt (`Approve? [y/n]`), approve on `y`, stream to terminal status, print the final report summary.
- **Verify:** `uv run sentinel demo` end-to-end.
- **Acceptance:** one command, no manual steps, finishes with `resolved`.

### Task 8.3 — `.env.example` + secrets sweep

- **Files:** `.env.example`
- **Does:** Every env var documented with a comment; real values nowhere.
- **Verify:** `grep -rn "sk-" --include="*.py" --include="*.yaml" --include="*.example" .` returns nothing; `git ls-files | xargs grep -l "api_key"` inspected manually — only references, never values.
- **Acceptance:** no secrets in the repo (attested in phase report).

### Task 8.4 — Final protocol audit

- **Files:** `scripts/check_protocols.py` (final config), `KNOWN_LIMITATIONS.md`, `LEARN_INDEX.md`
- **Does:** Full audit: every `TODO(review)` marker ↔ `KNOWN_LIMITATIONS.md` entry (both directions); every `LEARN[NN]` ↔ `LEARN_INDEX.md` row (both directions); LEARN numbering gapless; QS-1 5-field lint over every block; README limitations sentences match the user-visible entries; **spot-check three LEARN comments against the restate test (QS-3) and quote the verdicts in the final report**; **git audit: `git log --oneline` shows one commit per task across all phases in the `phase-N.M:` format, all nine `phase-N-complete` tags exist (`git tag -l 'phase-*-complete' | wc -l` → 9), working tree clean**.
- **Verify:** `uv run python scripts/check_protocols.py && grep -rn "TODO(review)" --include="*.py" --include="*.yaml" . | wc -l && grep -rn "LEARN\[" --include="*.py" --include="*.yaml" . && git tag -l 'phase-*-complete'`
- **Acceptance:** checker green; the final report contains the complete LEARN list (numbers + titles), the complete limitations list, the three restate-test spot-check verdicts, and the full commit/tag audit.

### Phase 8 acceptance (gate)

1. README walkthrough reproduces the demo from a clean clone.
2. Full audit green, including the QS-1 lint, the three QS-3 spot checks, and the git commit/tag audit.
3. Final report: all phase reports' LEARN/limitation tables consolidated, plus the §4-gate items 4a–4f for Phase 8 itself.
4. Git gate per GW-1…GW-3: commits `phase-8.1`…`phase-8.4` in the exact format, clean tree, then `git tag -a phase-8-complete -m "Docs & polish"`.

---

## 13. Risk Register (top 5)

| #   | Risk                                                                                               | Likelihood | Impact | Mitigation                                                                                                                                                                                                                                                   |
| --- | -------------------------------------------------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R1  | Local 7B model fails structured output                                                             | High       | High   | Uniform JSON+repair loop (D1) as the only path; schema-in-prompt + few-shot (Task 3.2); temperature 0 for logic calls; eval gate in mock AND live mode (Task 7.2) with prompt iteration budgeted in the task — thresholds never lowered silently             |
| R2  | langgraph / langgraph-checkpoint-postgres / langchain-openai version incompatibility               | Medium     | High   | Pinned versions verified on PyPI (2026-08-26); Task 0.1 runs `uv pip check`; Task 3.4's integration test round-trips a real `PostgresSaver` early. Re-verify command if a bump is forced: `uv pip check && uv run pytest tests/integration/test_graph.py -q` |
| R3  | Ollama unreachable from compose containers on Windows/WSL2 (`host.docker.internal`, `OLLAMA_HOST`) | Medium     | Medium | D4 topology fixed; smoke test (Task 0.5) covers the host path in Phase 0 and Phase 5 verifies the container path; README setup steps exact; compose `extra_hosts` set                                                                                        |
| R4  | Docker socket access from the executor container fails or is over-powerful                         | Medium     | Medium | Integration test in Task 4.3 proves socket access early; executor defaults to `dry_run=true`; whitelist enforced in executor code (not the LLM); risk documented in L2 limitation + the Task 4.3 LEARN deep-dive                                             |
| R5  | Metric-based verification flaky (5s scrape vs short chaos windows)                                 | Medium     | Low    | 5s scrape interval (D16); chaos `duration_seconds` defaults ≥ 120s; verification retries with backoff (D15); `/chaos/status` polling in tests instead of blind sleeps (Task 1.4)                                                                             |

---

## 14. Out-of-Scope List (each weakening item = pre-declared `KNOWN_LIMITATIONS.md` entry seeded in Phase 0)

| ID  | Out of scope / weakened                                                                                                                              | Limitation entry?                                          | Class         |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------- |
| L1  | Chaos suite covers container/process-level faults only — no network degradation (Toxiproxy), no disk fill in v1                                      | Yes                                                        | User-visible  |
| L2  | No authentication or authorization on any API endpoint (incl. approvals); Docker socket mounted into the API container — demo-only security posture  | Yes                                                        | User-visible  |
| L3  | Single-tenant, single API process; concurrent investigations are serialized; no horizontal scaling                                                   | Yes                                                        | User-visible  |
| L4  | Post-remediation verification is a fixed-window metric re-check; no statistical confirmation, no auto-rollback on flap                               | Yes                                                        | User-visible  |
| L5  | Grafana present only as an optional compose profile; no provisioned dashboards                                                                       | Yes                                                        | User-visible  |
| L6  | LangSmith tracing/eval-upload is a no-op without `LANGSMITH_API_KEY`                                                                                 | Yes                                                        | Internal-only |
| L7  | `scale_replicas` is partially emulated on plain Docker (no compose v2 dynamic scaling); returns `not_applicable` when replica containers don't exist | Yes — created in **Phase 4** (Task 4.3), pre-declared here | User-visible  |

Pure non-goals with no weakened user expectation (no entry needed): no Kubernetes, no multi-cluster, no production hardening, no UI beyond CLI/SSE (spec explicitly allows CLI).

---

## 15. Phase Order & Parallelization

```
Phase 0 (scaffold+protocols+git+LLM smoke)
   ├── Phase 1 (demo stack) ────────┐
   └── Phase 2 (data layer) ────────┤   1 ∥ 2 after 0
                                    ▼
              Phase 3 (agent core) ∥ Phase 4 (tools)   — 3 ∥ 4 once tool interfaces are stubbed (Task 3.1)
                                    ▼
              Phase 5 (API & HITL)  — needs 3 + 4 (+1 for live testing)
                                    ▼
              Phase 6 (verification loop) — small; may start while 5.4/5.5 finish
                                    ▼
              Phase 7 (evals & E2E) ▶ Phase 8 (docs & final audit)
```

Hard gates: no phase starts before its dependencies' acceptance gates pass; every phase ends with the protocol check, the §3.5 LEARN quality audit, the git gate (per-task commits, clean tree, `phase-N-complete` tag), and the phase report in the §4-gate format. Within phases, tasks touching disjoint files (e.g. 3.3 node tests ∥ 4.1/4.2 tool clients) may be parallelized by the executor — but commits are serialized in task order so GW-1's one-task-per-commit format survives (commit each task's files separately, in task order).

---

## 16. Execution Rules for the Coding Agent (binding)

1. Follow `PLAN.md`'s Working Protocol verbatim — including quality clauses QS-1…QS-6 and git-workflow clauses GW-1…GW-4 (§3.5). LEARN comments, the deferred-work protocol, and the git cadence are never optional and never themselves deferred.
2. LEARN numbering is global, zero-padded, strictly increasing, never reused, never deleted or renumbered by the executor; `LEARN_INDEX.md` updates in the same commit.
3. Every LEARN comment uses the full 5-field format (QS-1), teaches the concept thoroughly for a Java/Spring reader (QS-2), and must pass the restate test (QS-3). Before writing one, check `LEARN_INDEX.md` concept tags and cross-reference instead of duplicating (QS-4). A phase whose LEARN comments systematically restate the code is failed as a protocol violation.
4. Every `TODO(review)` marker ↔ `KNOWN_LIMITATIONS.md` entry, same commit; classification (user-visible → README sentence) per protocol.
5. **Git discipline (GW-1…GW-4):** commit after every completed task as `phase-N.M: <task title>`; tag `phase-N-complete` only after the phase gate passes; `git status --porcelain` must be empty at every phase boundary; never use `--no-verify` — the pre-commit protocol checker is load-bearing; the phase report lists every commit hash plus the tag. The repo lives on the WSL2 native filesystem (`~/dev2/Sentinel`), never `/mnt/c` (D17).
6. No silent scope cuts and no silent design decisions: anything not in this plan goes through one of the two protocols or stops for owner review.
7. Prompts live only in `src/sentinel/prompts/`, versioned, with design comments.
8. Explicit graph wiring only — no dynamic node/edge generation.
9. Each phase ends with: acceptance gate commands run and green, protocol check green (including QS-1 lint), LEARN quality audit (QS-1…QS-4), git gate green (GW-1…GW-3), and a phase report in the §4-gate format — including one LEARN comment quoted in full with a restate-test self-assessment (QS-6), individual justification of any under-floor comments (QS-3), and the commit evidence list (GW-4).
10. If a pinned version is unavailable, bump minimally, run the re-verify command in R2, and record it as an environment note in the phase report.
