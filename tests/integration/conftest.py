"""Integration fixtures. Require AQTA_TEST_DATABASE_URL pointing at a disposable database.

Each test that asks for ``migrated_db`` gets a freshly migrated schema (downgrade base + upgrade
head), because append-only tables cannot be truncated between tests by design.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from aqta.core.db import SessionFactory, create_engine, create_session_factory

ROOT = Path(__file__).resolve().parents[2]


def _db_url() -> str:
    url = os.environ.get("AQTA_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("AQTA_TEST_DATABASE_URL not set")
    return url


def _alembic(url: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed arguments, test-only
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def migrated_db() -> str:
    url = _db_url()
    _alembic(url, "downgrade", "base")
    _alembic(url, "upgrade", "head")
    return url


@pytest.fixture
async def engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(migrated_db)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(engine)
