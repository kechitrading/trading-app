"""Create a local .env from .env.example with random dev secrets. Never overwrites an existing .env.

Usage: uv run python scripts/init_env.py
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ("API_TOKEN", "APPROVAL_SECRET")


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; leaving it untouched")  # noqa: T201
        return 0
    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0]
        if key in GENERATED and line.endswith("="):
            line = f"{key}={secrets.token_urlsafe(32)}"
        lines.append(line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("created .env with random API_TOKEN and APPROVAL_SECRET (dev only)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
