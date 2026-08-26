# LEARN[11]: Alembic migrations for a Flyway/Liquibase user (mandatory — D7)
# Why this way: we hand-write the schema migration (0001_initial.py) and use Alembic purely as the
#   versioned runner (upgrade/downgrade), rather than autogenerating it from the ORM. Handwritten
#    gives us explicit, reviewable DDL and control over the tricky step: ADOPTING a pre-existing
#   table.
# Good sides:
#    - upgrade/downgrade map cleanly onto migrate/undo; Alembic tracks the current revision in a
#   table
#   - we control the exact DDL, including the pgvector extension and the shared deployments adoption
#   - the env resolves the DB URL from Settings, so Alembic and the app agree on which database
# Drawbacks:
#    - handwritten migrations drift from the ORM if you forget to update both (autogenerate would
#   catch
#     some drift but produces noisy diffs); we rely on the models mirroring the migration
#   - adopting a table two components created (Phase 1 services + this migration) is a coupling
#     decision, not a free lunch (see LEARN[09])
# Concept: Alembic is the Python analogue of Flyway/Liquibase — a versioned, ordered chain of schema
#   migrations. upgrade() applies the next step, downgrade() undoes it, and an alembic_version table
#    records where you are, so `alembic upgrade head` brings any environment forward
#   deterministically.
#   We deliberately do NOT autogenerate: for a simple fixed schema, explicit DDL is easier to review
#    and lets us run `CREATE EXTENSION IF NOT EXISTS vector` and adopt the Phase 1 `deployments`
#   table
#   (which the demo services already created via `CREATE TABLE IF NOT EXISTS`). Adopting means the
#   migration creates it if missing and does NOT alter it if present — the migration must not assume
#    exclusive ownership of a table two components share. In a Java shop this is the difference
#   between
#   a Flyway migration and a "baseline" migration that reconciles with a pre-existing schema: you
#   assert/derive the expected shape rather than force-recreate it. round-trip testing
#   (upgrade head / downgrade base / upgrade head) is what proves the chain is reversible.
# See also: LEARN[09] (shared deployments table), LEARN[12] (embeddings/pgvector)
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the app schema; adopt (or create) the shared `deployments` table; enable pgvector."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "incidents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_name", sa.Text(), nullable=False),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("raw_alert", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('investigating','awaiting_approval','remediating','verifying',"
            "'resolved','escalated','rejected')",
            name="ck_incidents_status",
        ),
    )

    # Adopt the Phase 1 `deployments` table: create it if the demo services have not already done
    # so, and never alter it if it exists (it is shared with demo_stack — see LEARN[09]).
    op.execute(
        "CREATE TABLE IF NOT EXISTS deployments ("
        " id bigserial PRIMARY KEY, service text NOT NULL, version text NOT NULL,"
        " event text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
    )

    op.create_table(
        "agent_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", UUID(as_uuid=True), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "runbooks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
    )


def downgrade() -> None:
    """Drop the app schema in reverse order (extension dropped last)."""
    op.drop_table("runbooks")
    op.drop_table("agent_events")
    op.execute("DROP TABLE IF EXISTS deployments")
    op.drop_table("incidents")
    op.execute("DROP EXTENSION IF EXISTS vector")
