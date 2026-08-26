"""Runbook ingestion: chunk -> embed -> upsert into the `runbooks` table (PLAN.md Task 2.3).

Idempotent re-runs: each chunk gets a stable ``sha256`` content hash and is upserted with
``ON CONFLICT (content_hash)``, so re-ingesting never creates duplicate rows (D2 embeddings are
provider-independent local models — see LEARN[12]).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sentinel.config import Settings
from sentinel.db.models import Runbook
from sentinel.db.session import create_engine_from_url, make_session_factory
from sentinel.rag.embeddings import embed_texts

DEFAULT_RUNBOOKS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "runbooks"


def split_sections(content: str) -> list[tuple[str, str]]:
    """Split a runbook into (section heading, section body) pairs by ``## `` headings."""
    headings: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current_heading is not None:
                headings.append((current_heading, current_lines))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_heading is not None:
        headings.append((current_heading, current_lines))
    return [(h, "\n".join(lines).strip()) for h, lines in headings if "\n".join(lines).strip()]


def chunk_runbooks(paths: Sequence[Path]) -> list[dict[str, str]]:
    """Chunk each runbook into a whole-doc chunk plus one chunk per ``##`` section."""
    chunks: list[dict[str, str]] = []
    for path in sorted(paths):
        content = path.read_text(encoding="utf-8").strip()
        stem = path.stem
        chunks.append({"title": stem, "content": content})
        for heading, body in split_sections(content):
            chunks.append({"title": f"{stem}: {heading}", "content": body})
    return chunks


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _upsert_statement(title: str, content: str, embedding: list[float]) -> Insert:
    """Build an idempotent INSERT ... ON CONFLICT (content_hash) statement."""
    stmt = pg_insert(Runbook).values(
        title=title,
        content=content,
        content_hash=_content_hash(content),
        embedding=embedding,
    )
    return stmt.on_conflict_do_update(
        index_elements=["content_hash"],
        set_={"embedding": stmt.excluded.embedding, "title": stmt.excluded.title},
    )


def iter_chunks(runbooks_dir: Path) -> Iterator[dict[str, str]]:
    """Iterate chunks for every ``*.md`` runbook in ``runbooks_dir``."""
    yield from chunk_runbooks(list(runbooks_dir.glob("*.md")))


def ingest_runbooks(
    runbooks_dir: Path | None = None,
    session_factory: Callable[[], AbstractContextManager[Any]] | None = None,  # injected for tests
    settings: Settings | None = None,
) -> int:
    """Ingest all runbooks; returns the number of chunks upserted."""
    if session_factory is None:
        settings = settings or Settings()
        engine = create_engine_from_url(settings.database.url)
        session_factory = make_session_factory(engine)

    runbooks_dir = runbooks_dir or DEFAULT_RUNBOOKS_DIR
    chunks = list(iter_chunks(runbooks_dir))
    vectors = embed_texts([c["content"] for c in chunks])

    with session_factory() as session:
        for chunk, vec in zip(chunks, vectors, strict=True):
            session.execute(_upsert_statement(chunk["title"], chunk["content"], vec))
        session.commit()
    return len(chunks)
