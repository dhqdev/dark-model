from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool, text

from app import models  # noqa: F401 - registra as tabelas
from app.config import get_settings
from app.db import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().resolved_database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        is_pg = connection.dialect.name == "postgresql"
        if is_pg:
            # evita duas migrações simultâneas (ex.: duas réplicas da API)
            connection.execute(text("SELECT pg_advisory_lock(727274)"))
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata,
                              render_as_batch=not is_pg, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_pg:
                connection.execute(text("SELECT pg_advisory_unlock(727274)"))
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
