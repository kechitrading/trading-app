"""``python -m aqta.audit verify`` - recompute the audit hash chain; exit 1 on any break."""

from __future__ import annotations

import argparse
import asyncio
import sys

from aqta.audit.service import SqlAuditLog
from aqta.core.db import create_engine, create_session_factory
from aqta.core.settings import get_settings


async def run_verify(database_url: str) -> int:
    engine = create_engine(database_url)
    try:
        result = await SqlAuditLog(create_session_factory(engine)).verify()
    finally:
        await engine.dispose()
    if result.ok:
        print(f"audit chain OK: {result.checked} entries, head={result.head_hash}")  # noqa: T201
        return 0
    print(f"audit chain BROKEN: {len(result.errors)} problem(s) in {result.checked} entries")  # noqa: T201
    for err in result.errors:
        print(f"  - {err}")  # noqa: T201
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aqta.audit")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="Recompute and check the audit hash chain")
    verify.add_argument("--database-url", default=None, help="Defaults to DATABASE_URL")
    args = parser.parse_args(argv)

    url = args.database_url or get_settings().database_url.get_secret_value()
    return asyncio.run(run_verify(url))


if __name__ == "__main__":
    sys.exit(main())
