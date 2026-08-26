"""Add a unique content_hash column to runbooks for idempotent ingestion (Task 2.3).

``ingest-runbooks`` computes a stable hash of each chunk and upserts on it (ON CONFLICT), so
re-running ingestion never creates duplicate rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runbooks", sa.Column("content_hash", sa.Text(), nullable=True))
    # Backfill (there should be no rows yet) then enforce NOT NULL + unique on a fresh ingest key.
    op.create_unique_constraint("uq_runbooks_content_hash", "runbooks", ["content_hash"])
    op.alter_column("runbooks", "content_hash", existing_type=sa.Text(), nullable=False)


def downgrade() -> None:
    op.drop_constraint("uq_runbooks_content_hash", "runbooks", type_="unique")
    op.drop_column("runbooks", "content_hash")
