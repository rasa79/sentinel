# LEARN[05]: one langchain-openai client for both cloud APIs and local Ollama (for a Java engineer)
# Why this way: instead of two provider-specific clients, we always use langchain_openai.ChatOpenAI
#   and only vary the base_url / api_key / model. This works because Ollama exposes an OpenAI-
#   compatible /v1 API surface, so the same client speaks to OpenAI/Anthropic-compatible cloud
#   endpoints and to a local model unchanged.
# Good sides:
#   - a single code path to trust and test; switching providers is config, not code
#   - local/cloud parity: embeddings (D2) and the structured-output loop (D1) behave identically
#   - the config object already carries base_url/model/api_key_env, so no hard-coded endpoints
# Drawbacks:
#   - only OpenAI-compatible providers work; a truly different API (native Anthropic) would need
#     a separate client and a factory with an if/else, which we deliberately avoid in v1
#   - API-key differences are lossy: Ollama ignores the key, but the factory still supplies one,
#     so tooling that assumes a real key might be surprised in local mode
# Concept: ChatOpenAI is a thin wrapper over the OpenAI chat-completions protocol. Because
#   Ollama ships /v1/chat/completions, a ChatOpenAI pointed at http://localhost:11434/v1 with any
#   dummy api_key is a valid OpenAI-compatible client. The factory gets base_url, model,
#   temperature from settings and reads the real key from the env var named by api_key_env —
#   never committing a key. "api_key_env" is deliberately a *name*, so the repo stores no
#   credential. The 'dummy key accepted for Ollama' note is the key subtlety: the OpenAI protocol
#   demands an Authorization header, but a local server ignores its value, so we always pass a
#   token (placeholder for Ollama, real key for cloud). This mirrors how Spring's RestClient/
#   WebClient can be pointed at different hosts with one bean — the difference is config.
# See also: LEARN[04] (structured output repair loop), LEARN[03] (config layering)
from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from sentinel.config import Settings


def get_chat_model(settings: Settings) -> ChatOpenAI:
    """Build a ``ChatOpenAI`` client from settings (D3).

    For the local provider the key is a placeholder: Ollama's OpenAI-compatible server ignores
    it, but the protocol still requires an Authorization header. For cloud, a real key must be
    present in the env var named by ``settings.llm.api_key_env``.

    D14 (zero-manual-steps): ``settings`` reads ``.env`` for its fields, but the API key is consumed
    here via ``os.environ`` (it is not a Settings field). pydantic-settings does not populate
    ``os.environ``, so a host-side process would otherwise need to ``source .env`` first.
    ``load_dotenv`` loads ``.env`` into ``os.environ`` without overriding already-set vars, so
    ``uv run sentinel evals run`` (and any direct factory use) needs no manual step.
    """
    load_dotenv()
    llm = settings.llm
    api_key = os.environ.get(
        llm.api_key_env,
        "ollama-placeholder-key",
    )
    return ChatOpenAI(
        model=llm.model,
        base_url=llm.base_url,
        api_key=SecretStr(api_key),
        temperature=llm.temperature,
    )
