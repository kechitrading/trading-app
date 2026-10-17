"""Alembic environment (async). URL from ``-x url=...`` or settings.DATABASE_URL."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy.engine import Connection

# Import every ORM model so autogenerate sees the full metadata.
import aqta.astrology.models
import aqta.audit.models
import aqta.execution.models
import aqta.forecasting.models
import aqta.ingestion.models
import aqta.learning.models
import aqta.proposals.models
import aqta.risk.models
import aqta.strategy.models  # noqa: F401
from aqta.core.db import Base, create_engine
from aqta.core.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    return x_args.get("url") or get_settings().database_url.get_secret_value()


def _include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # Timescale creates internal objects; never let autogenerate try to drop them.
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=_include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
