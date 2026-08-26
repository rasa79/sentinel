"""Unit tests for the uniform JSON + validate + repair structured-output loop (D1)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from sentinel.llm.structured import (
    MAX_RETRIES,
    StructuredOutputError,
    structured_call,
)


class Person(BaseModel):
    """Tiny schema used to exercise the structured-output loop."""

    name: str
    age: int


class FakeModel:
    """Duck-typed stand-in for a chat model that returns a scripted sequence of strings."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: int = 0

    def invoke(self, prompt: str) -> AIMessage:  # noqa: ARG002 - signature matches BaseChatModel
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return AIMessage(content=self._responses[idx])


def test_clean_json_parses() -> None:
    model = FakeModel(['{"name": "Alice", "age": 30}'])
    result = structured_call(model, "Extract a person.", Person)
    assert result == Person(name="Alice", age=30)


def test_fenced_json_parses() -> None:
    model = FakeModel(['```json\n{"name": "Bob", "age": 25}\n```'])
    result = structured_call(model, "Extract a person.", Person)
    assert result == Person(name="Bob", age=25)


def test_json_with_surrounding_prose_parses() -> None:
    model = FakeModel(['Here is the answer: {"name": "Carol", "age": 40} (that is all).'])
    result = structured_call(model, "Extract a person.", Person)
    assert result == Person(name="Carol", age=40)


def test_repaired_after_one_retry() -> None:
    model = FakeModel(["not json at all", '{"name": "Dave", "age": 22}'])
    result = structured_call(model, "Extract a person.", Person)
    assert result == Person(name="Dave", age=22)
    assert model.calls == 2  # initial + 1 repair


def test_hard_failure_after_retry_budget() -> None:
    model = FakeModel(["nope", "still nope", "and nope"])
    with pytest.raises(StructuredOutputError):
        structured_call(model, "Extract a person.", Person)
    assert model.calls == MAX_RETRIES + 1


def test_retry_budget_is_two_by_default() -> None:
    """The retry budget is exactly 2 (invoked up to 3 times total), constant-only."""
    assert MAX_RETRIES == 2


def test_validation_error_is_repairable() -> None:
    # First response is valid JSON but fails schema validation (age is a string) -> one repair.
    model = FakeModel(['{"name": "Eve", "age": "thirty"}', '{"name": "Eve", "age": 33}'])
    result = structured_call(model, "Extract a person.", Person)
    assert result == Person(name="Eve", age=33)
