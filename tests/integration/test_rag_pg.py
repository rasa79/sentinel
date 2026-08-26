"""Integration test for runbook retrieval against the real compose Postgres + local embedder.

Requires the demo stack (``docker compose up -d postgres``) since it hits the real ``runbooks``
table and the all-MiniLM-L6-v2 model. Marked ``integration``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from sentinel.config import Settings
from sentinel.db.models import Runbook
from sentinel.db.session import create_engine_from_url, make_session_factory
from sentinel.rag.embeddings import embed_texts
from sentinel.rag.retrieve import retrieve_runbooks

pytestmark = pytest.mark.integration

FIXTURES = [
    (
        "itest-kafka-consumer-lag",
        "A Kafka consumer is lagging badly because the producer throughput exceeds the consumer "
        "processing rate.",
    ),
    (
        "itest-s3-corruption",
        "Objects in an S3 bucket are corrupted; read requests return checksum mismatches.",
    ),
]


@pytest.fixture
def db_session_factory():  # type: ignore[no-untyped-def]
    settings = Settings()
    engine = create_engine_from_url(settings.database.url)
    return make_session_factory(engine)


def test_retrieval_returns_the_matching_fixture_first(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    vecs = embed_texts([content for _, content in FIXTURES])
    with db_session_factory() as session:
        for (title, content), vec in zip(FIXTURES, vecs, strict=True):
            session.add(
                Runbook(
                    title=title, content=content, content_hash=f"itest-hash-{title}", embedding=vec
                )
            )
        session.commit()

    try:
        # Each hand-written query should be answered by its matching fixture (top hit).
        kafka_hits = retrieve_runbooks(
            "kafka consumer lag due to producer throughput",
            k=5,
            min_score=0.0,
            session_factory=db_session_factory,
        )
        assert kafka_hits[0].title == "itest-kafka-consumer-lag", [h.title for h in kafka_hits]

        s3_hits = retrieve_runbooks(
            "s3 object corruption checksum mismatch",
            k=5,
            min_score=0.0,
            session_factory=db_session_factory,
        )
        assert s3_hits[0].title == "itest-s3-corruption", [h.title for h in s3_hits]
    finally:
        with db_session_factory() as session:
            titles = [t for t, _ in FIXTURES]
            session.execute(delete(Runbook).where(Runbook.title.in_(titles)))
            session.commit()
        # sanity: no test rows remain
        with db_session_factory() as session:
            remaining = (
                session.execute(select(Runbook.id).where(Runbook.title.in_(titles))).scalars().all()
            )
        assert remaining == []


# Each chaos type must be answerable by its own runbook (Phase 2 gate item 2).
_CHAOS_QUERIES = {
    "latency": ("latency-spike-downstream", "high latency spike on the orders service"),
    "error_burst": (
        "error-burst-after-deploy",
        "why is the service returning a burst of 5xx errors",
    ),
    "memory_leak": ("memory-leak-slow-growth", "memory usage keeps growing slowly and never drops"),
    "bad_deploy": ("bad-deploy-rollback", "the deployment looks bad and the service is degraded"),
}


def test_retrieval_returns_chaos_matching_runbook(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    for expected, query in _CHAOS_QUERIES.values():
        hits = retrieve_runbooks(query, k=5, min_score=0.0, session_factory=db_session_factory)
        tops = [h.title for h in hits[:3]]
        assert any(expected in t for t in tops), f"expected {expected!r} in {tops}"
