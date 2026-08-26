"""Unit tests for runbook retrieval (PLAN.md Task 2.4) — model and DB are mocked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from sentinel.rag.retrieve import retrieve_runbooks


class _FakeResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows
        self.executed: list[object] = []

    def execute(self, stmt: object) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self._rows)

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def test_retrieve_returns_ranked_hits_with_scores(monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sentinel.rag.retrieve.embed_texts", lambda texts: [[0.5] * 384 for _ in texts]
    )
    rows = [
        SimpleNamespace(title="latency", content="Latency runbook content here.", distance=0.2),
        SimpleNamespace(title="memory", content="Memory runbook content here.", distance=0.5),
    ]
    session = _FakeSession(rows)

    hits = retrieve_runbooks(query="q", k=10, min_score=0.0, session_factory=lambda: session)
    assert [h.title for h in hits] == ["latency", "memory"]
    assert hits[0].score == pytest.approx(0.8)  # 1 - distance
    assert hits[1].score == pytest.approx(0.5)
    assert hits[0].snippet  # non-empty snippet


def test_retrieve_sql_applies_cosine_distance_k_and_floor(monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sentinel.rag.retrieve.embed_texts", lambda texts: [[0.5] * 384 for _ in texts]
    )
    session = _FakeSession([])

    retrieve_runbooks(query="q", k=3, min_score=0.3, session_factory=lambda: session)
    stmt = session.executed[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]
    assert "cosine_distance" in sql or "<=>" in sql  # cosine distance operator
    assert "LIMIT" in sql
    assert "<=" in sql  # the score-floor WHERE clause
