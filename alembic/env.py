"""Alembic environment (PLAN.md Task 2.1).

The migration target URL comes from ``Settings`` (D14) so Alembic and the app always point at the
same database, and it endorses the same config precedence (env vars > config.yaml > defaults).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Engine, create_engine, pool

from sentinel.config import Settings
from sentinel.db.models import Base
from sentinel.db.session import ensure_psycopg_driver

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the target URL from settings (env > .env > config.yaml > defaults).
_settings = Settings()
config.set_main_option("sqlalchemy.url", _settings.database.url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode (connect to the DB)."""
    provided = config.attributes.get("connection", None)
    engine: Engine
    if isinstance(provided, Engine):
        engine = provided
    else:
        engine = create_engine(
            ensure_psycopg_driver(config.get_main_option("sqlalchemy.url")),
            poolclass=pool.NullPool,
        )

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
