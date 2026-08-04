"""Alembic environment for the Raw Store.

This SQLAlchemy Engine exists ONLY for alembic's own connection/transaction
handling. Migration scripts use op.execute() with raw SQL -- no ORM, no
SQLAlchemy Core table constructs. The application's own repository
(stores/raw_store/repository.py) never imports SQLAlchemy; it talks to
this same .sqlite file directly via the stdlib sqlite3 module.

DB path resolution: MNEMOSYNE_RAW_STORE_DB env var if set, else the
sqlalchemy.url default in alembic.ini (local-CLI convenience only).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_path = os.environ.get("MNEMOSYNE_RAW_STORE_DB")
if db_path:
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

target_metadata = None  # no ORM models to autogenerate against; migrations are hand-written


def run_migrations_offline() -> None:
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
