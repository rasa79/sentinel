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
