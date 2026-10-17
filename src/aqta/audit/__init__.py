"""Append-only, hash-chained audit log (FR-054, NFR-011).

Public API: ``AuditSink`` (port), ``SqlAuditLog``, ``InMemoryAuditLog``, ``verify_chain``.
CLI: ``python -m aqta.audit verify``.
"""

from aqta.audit.chain import (
    GENESIS_HASH,
    AuditEntry,
    ChainVerification,
    compute_hash,
    verify_chain,
)
from aqta.audit.service import AuditSink, InMemoryAuditLog, SqlAuditLog

__all__ = [
    "GENESIS_HASH",
    "AuditEntry",
    "AuditSink",
    "ChainVerification",
    "InMemoryAuditLog",
    "SqlAuditLog",
    "compute_hash",
    "verify_chain",
]
