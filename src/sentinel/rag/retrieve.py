#  LEARN[13]: retrieval — query-time embedding symmetry and the score floor (QS-4 cross-ref to
# LEARN[12])
# Why this way: retrieve_runbooks embeds the QUERY with the same local model used for the corpus,
#   then selects by cosine distance (`embedding <=> query`). This is a labeled cross-reference stub:
#   the embedding/vector fundamentals live in LEARN[12]; here we add only what retrieval adds.
# Good sides:
#   - same model for corpus and query, so cosine distance is meaningful (see LEARN[12])
#   - k and a min-score floor come from config, so noise can be filtered rather than always returned
# Drawbacks:
#   - cosine distance is order-of-magnitude fine but a weak semantic signal on a tiny corpus
#   - a min-score floor that is too high returns an empty context (agent gets nothing to cite)
# Concept: at query time you MUST embed with the identical encoder used at ingest; otherwise the
#    vectors live in different spaces and `<=>` is meaningless (the symmetry requirement). We then
#   sort
#   by cosine distance ascending and keep the top-k. The score floor is the other knob: score is
#    1 - distance (for normalized vectors, cosine similarity equals 1 - cosine distance), and
#   dropping
#    hits below the floor keeps irrelevant chunks out of the context window. The trade-off is the
#   flip
#    side of LEARN[12]'s embedding choice — too low a floor adds noise, too high a floor yields an
#   empty
#   result. The snippet is a short whitespace-normalized prefix of the matched chunk.
# See also: LEARN[12] (embeddings / vector search), the score floor in config RAG settings
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from sentinel.config import Settings
from sentinel.db.models import Runbook
from sentinel.db.session import create_engine_from_url, make_session_factory
from sentinel.rag.embeddings import embed_texts

_DEFAULT_K = 3
_DEFAULT_MIN_SCORE = 0.3


class RunbookHit(BaseModel):
    """A retrieved runbook match: title, a snippet, and a cosine-similarity score in [0, 1]."""

    title: str
    snippet: str
    score: float


def _snippet(content: str, limit: int = 160) -> str:
    text = " ".join(content.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def retrieve_runbooks(
    query: str,
    k: int | None = None,
    min_score: float | None = None,
    settings: Settings | None = None,
    session_factory: Callable[[], AbstractContextManager[Any]] | None = None,  # injected for tests
) -> list[RunbookHit]:
    """Return the top-k runbook hits for ``query``, ordered by cosine similarity (descending)."""
    if settings is None and session_factory is None:
        settings = Settings()
    if session_factory is None:
        assert settings is not None
        engine = create_engine_from_url(settings.database.url)
        session_factory = make_session_factory(engine)

    config_k = settings.rag.top_k if settings is not None else None
    config_min = settings.rag.min_score if settings is not None else None
    k = k if k is not None else (config_k if config_k is not None else _DEFAULT_K)
    min_score = (
        min_score
        if min_score is not None
        else (config_min if config_min is not None else _DEFAULT_MIN_SCORE)
    )

    query_vec = embed_texts([query])[0]
    distance = Runbook.embedding.cosine_distance(query_vec)
    stmt = (
        select(Runbook.title, Runbook.content, distance.label("distance"))
        .where(distance <= 1.0 - min_score)
        .order_by(distance.asc())
        .limit(k)
    )

    with session_factory() as session:
        rows = session.execute(stmt).all()

    return [
        RunbookHit(
            title=row.title, snippet=_snippet(row.content), score=max(0.0, 1.0 - row.distance)
        )
        for row in rows
    ]
