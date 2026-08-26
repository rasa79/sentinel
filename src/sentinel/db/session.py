"""SQLAlchemy engine/session factory for Sentinel (PLAN.md Task 2.1)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def ensure_psycopg_driver(url: str) -> str:
    """Force SQLAlchemy to use the psycopg (v3) driver.

    A plain ``postgresql://`` URL makes SQLAlchemy default to psycopg2, which is not installed.
    ``postgresql+psycopg://`` selects the psycopg v3 dialect (D7 uses a psycopg connection pool).
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def create_engine_from_url(database_url: str) -> Engine:
    """Create an engine with pool pre-ping so stale connections are transparently replaced."""
    return create_engine(ensure_psycopg_driver(database_url), pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to ``engine`` (no autoflush; don't expire on commit)."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
