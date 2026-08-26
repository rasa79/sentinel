"""Unit tests for runbook chunking and idempotent upsert (PLAN.md Task 2.3)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.dialects import postgresql

from sentinel.rag.ingest import (
    _content_hash,
    chunk_runbooks,
    ingest_runbooks,
    split_sections,
)


class _FakeSession:
    """Records executed statements; never touches a real DB."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.committed = False

    def execute(self, stmt: object) -> None:
        self.executed.append(stmt)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSession:
        return self._session


def test_split_sections_splits_on_h2_headings() -> None:
    content = "# T\n## S1\nbody1\n## S2\nbody2\n"
    assert split_sections(content) == [("S1", "body1"), ("S2", "body2")]


def test_chunk_runbooks_whole_doc_plus_sections(tmp_path: Path) -> None:
    rb = tmp_path / "runbooks"
    rb.mkdir()
    (rb / "a.md").write_text("# A\n## S1\nbody1\n## S2\nbody2\n", encoding="utf-8")
    (rb / "b.md").write_text("# B\n## S1\nbodyB\n", encoding="utf-8")

    chunks = chunk_runbooks([rb / "a.md", rb / "b.md"])
    titles = [c["title"] for c in chunks]
    assert titles == ["a", "a: S1", "a: S2", "b", "b: S1"]  # whole doc + per sections
    assert chunks[0]["content"].startswith("# A")


def test_content_hash_is_stable() -> None:
    assert _content_hash("same") == _content_hash("same")
    assert _content_hash("same") != _content_hash("different")


def test_ingest_uses_content_hash_upsert_with_mocked_model(
    monkeypatch: object, tmp_path: Path
) -> None:
    """The model is mocked; we assert the upsert-on-content_hash logic against a fake session."""
    rb = tmp_path / "runbooks"
    rb.mkdir()
    (rb / "a.md").write_text("# A\n## S1\nbody1\n## S2\nbody2\n", encoding="utf-8")

    monkeypatch.setattr(
        "sentinel.rag.ingest.embed_texts",  # type: ignore[attr-defined]
        lambda texts: [[0.1] * 384 for _ in texts],
    )
    session = _FakeSession()
    factory = _FakeFactory(session)

    n = ingest_runbooks(runbooks_dir=rb, session_factory=factory)
    assert n == 3  # whole doc + 2 sections
    assert session.committed
    assert len(session.executed) == 3

    for stmt in session.executed:
        compiled = str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]
        assert "ON CONFLICT (content_hash) DO UPDATE SET" in compiled
