# LEARN INDEX

Numbered, gapless, zero-padded index of all `LEARN[NN]` comments in the codebase. Every row must
correspond to a `# LEARN[NN]:` block in the code (scanned by `scripts/check_protocols.py`), and
every code block must have a row here. Concept tags are used for the cross-reference rule (QS-4).

| Num      | Title                                                                       | File:Line                        | Concept tags                                                   |
| -------- | --------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------- |
| LEARN[01] | uv + pyproject.toml packaging/sync model (for a Maven/Gradle engineer)       | pyproject.toml:1                  | python packaging; uv; lockfile; PEP 621; entry points          |
| LEARN[02] | Repo on the WSL2 native filesystem, not /mnt/c (deep-dive, D17)              | .gitignore:1                      | 9P mount; ext4 vs NTFS; core.autocrlf; core.filemode; WSL2     |
| LEARN[03] | Configuration layering with pydantic-settings (Spring application.yml)       | src/sentinel/config.py:1          | config precedence; pydantic-settings; twelve-factor; env vars  |
| LEARN[04] | Uniform JSON→extract→validate→repair structured output (deep-dive, D1)       | src/sentinel/llm/structured.py:1  | structured output; prompt-and-parse; repair loop; Pydantic     |
| LEARN[05] | One langchain-openai client for cloud and local Ollama (D3)                  | src/sentinel/llm/factory.py:1     | OpenAI-compatible API; provider abstraction; base_url; api key |
| LEARN[06] | host.docker.internal vs localhost from containers (Docker Desktop/WSL2, D4)  | scripts/smoke_llm.py:1            | docker networking; host-gateway; namespace isolation; WSL2     |
| LEARN[07] | Chaos-as-a-deterministic-state-machine (process-local chaos state)                | demo_stack/services/common.py:1   | chaos injection; state machine; fault injection; reset timer    |
| LEARN[08] | prometheus-client metric types (Counter vs Histogram vs Gauge)                    | demo_stack/services/common.py:68  | prometheus-client; counter; histogram; gauge; metrics           |
| LEARN[09] | Demo services write deploy events directly to the shared DB (D8)                       | demo_stack/services/common.py:176 | shared-database pattern; deploy events; psycopg; schema coupling |
| LEARN[10] | Push-vs-pull logging — toy services push directly to Loki (D10 context)                  | demo_stack/services/common.py:250 | log aggregation; Loki push API; Promtail/agent; buffering gaps     |
| LEARN[11] | Alembic migrations for a Flyway/Liquibase user (D7)                                          | alembic/versions/0001_initial.py:1 | alembic; upgrade/downgrade; schema migration; baseline/adoption   |
| LEARN[12] | Why embeddings are provider-independent local models; vector search (deep-dive, D2)              | src/sentinel/rag/embeddings.py:1   | embeddings; cosine similarity; sentence-transformers; pgvector    |
| LEARN[13] | Retrieval: query-time embedding symmetry + score floor (QS-4 cross-ref to LEARN[12])                 | src/sentinel/rag/retrieve.py:1     | retrieval; cosine distance; top-k; score floor                    |
| LEARN[14] | LangGraph state (TypedDict + reducers) vs a Spring workflow context object                            | src/sentinel/agent/state.py:1      | langgraph; state channels; reducers; checkpointing                 |
| LEARN[15] | extra="forbid" as a contract boundary against LLM hallucination                                       | src/sentinel/agent/schemas.py:1    | pydantic; extra=forbid; LLM contract; DTO strictness              |
| LEARN[16] | Prompt design for weak models: schema-in-prompt + few-shot + repair loop (QS-4 cross-ref)    | src/sentinel/prompts/__init__.py:1 | prompt design; few-shot; schema-in-prompt; prompt versioning      |
| LEARN[17] | DI via LangGraph config["configurable"] vs constructor injection                                | src/sentinel/agent/nodes/triage.py:1 | dependency injection; langgraph config; testability; run config    |
| LEARN[18] | What interrupt() actually does at a node (D6 part 1 of 2)                                      | src/sentinel/agent/nodes/human_gate.py:1 | interrupt; cooperative suspension; graph suspend/resume; human task |
| LEARN[19] | The Postgres checkpointer vs an in-memory saver (D5, deep-dive)                                    | src/sentinel/agent/graph.py:1      | checkpointer; checkpoint; thread_id; PostgresSaver; durability     |
| LEARN[20] | interrupt/Command(resume) vs an API polling loop (D6, deep-dive)                                   | src/sentinel/agent/graph.py:38     | resumable suspension; polling; single-writer; BPMN wait-state      |
| LEARN[21] | Retry policy design: 3 attempts + exponential backoff, transient-only (D9)                          | src/sentinel/tools/loki.py:1       | retry; backoff; transient vs permanent; tenacity; httpx            |
| LEARN[22] | PromQL notes: rate(), histogram quantiles, empty results are data (QS-4 cross-ref)                | src/sentinel/tools/prometheus.py:1 | PromQL; rate; histogram_quantile; gauge; empty-result-as-data       |
| LEARN[23] | Whitelist + dry-run in the executor: the capability gate for agent actions (D11, deep-dive)      | src/sentinel/tools/executor.py:1   | capability gating; whitelist; dry-run; docker socket; authorization |
| LEARN[24] | Background asyncio task vs a task queue (Celery/Temporal) for the investigation run               | src/sentinel/api/routes_alerts.py:1 | asyncio task; task queue; fire-and-forget; durability; retry       |
| LEARN[25] | Alertmanager v4 webhook payload and the dedupe choice                                              | src/sentinel/api/routes_alerts.py:32 | alertmanager; webhook; labels; dedupe; idempotency key             |
| LEARN[26] | Resume through the checkpointer, the 409 guard, and concurrent approvals (QS-4 cross-ref)       | src/sentinel/api/routes_incidents.py:132 | approval; resume; 409 guard; checkpoint; concurrency/race           |
| LEARN[27] | SSE vs WebSocket, and the replay-then-live dedupe (deep-dive, D10)                                  | src/sentinel/api/routes_stream.py:28   | SSE; WebSocket; replay-then-live; event bus; streaming; dedupe        |
| LEARN[28] | Empty-is-suspicious vs empty-is-clean: gather retry under observability lag (deep-dive)                  | src/sentinel/agent/evidence.py:15      | observability lag; empty-is-suspicious; retry; scrape; gather nodes    |
| LEARN[29] | Fixed-window verification re-check vs continuous watch (deep-dive, D15)                                   | src/sentinel/agent/nodes/verify.py:10  | verification; fixed-window; re-check; escalation; L4 (pairing)          |
