"""SQLAlchemy ORM models for the Sentinel app schema (PLAN.md Task 2.1).

These mirror the Alembic migration (``alembic/versions/0001_initial.py``). The ``deployments``
table is intentionally ADOPTED from the Phase 1 demo services (which create it via
``CREATE TABLE IF NOT EXISTS``); this model reflects that same schema without altering it (D7).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

INCIDENT_STATUSES = (
    "investigating",
    "awaiting_approval",
    "remediating",
    "verifying",
    "resolved",
    "escalated",
    "rejected",
)


class Base(DeclarativeBase):
    """Declarative base for all Sentinel ORM models."""


class Incident(Base):
    """An incoming alert mapped to a triage incident (status per :data:`INCIDENT_STATUSES`)."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_name: Mapped[str] = mapped_column(Text, nullable=False)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_alert: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('investigating','awaiting_approval','remediating','verifying',"
            "'resolved','escalated','rejected')",
            name="ck_incidents_status",
        ),
    )


class Deployment(Base):
    """A deploy event written by the demo services (adopted from Phase 1, D8)."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentEvent(Base):
    """An event emitted by the agent graph (D10) — the ordered trace for an incident."""

    __tablename__ = "agent_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False
    )
    node: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Runbook(Base):
    """A runbook document plus its pgvector embedding (D2: 384-dim)."""

    __tablename__ = "runbooks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
