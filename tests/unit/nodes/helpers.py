"""Shared helpers for node unit tests (PLAN.md Task 3.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "llm"


class FakeLLM:
    """A chat-model stand-in that returns a recorded JSON response (see tests/fixtures/llm)."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    def invoke(self, prompt: str, **kwargs: object) -> AIMessage:  # noqa: ARG002
        self.calls += 1
        return AIMessage(content=self._response)


def load_response(fixture_name: str) -> str:
    """Load the canned LLM response string from a fixture JSON file."""
    return json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))["response"]


def make_config(response: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build a RunnableConfig-style dict; optionally inject a FakeLLM and extra values."""
    config: dict[str, Any] = {"configurable": dict(extra)}
    if response is not None:
        config["configurable"]["llm"] = FakeLLM(response)
    return config
