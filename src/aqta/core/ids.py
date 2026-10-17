"""Identifier helpers. Prefixed ids make logs and audit rows easy to read."""

from __future__ import annotations

import secrets
import uuid


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}_{value}" if prefix else value


def new_nonce(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)
