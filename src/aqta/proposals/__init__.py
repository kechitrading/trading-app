"""Trade proposals, lifecycle and approval tokens (BR-002, BR-003, FR-011, FR-023, FR-024).

Must not import signals/forecasting/astrology: execution depends on this package and RULE-013 keeps
execution isolated from analysis.
"""

from aqta.proposals.lifecycle import (
    ApprovalService,
    Horizon,
    Proposal,
    ProposalStatus,
    transition,
)
from aqta.proposals.tokens import (
    ApprovalClaims,
    ApprovalTokenError,
    ApprovalTokenService,
    InMemoryNonceStore,
    NonceStore,
    TokenFailure,
)

__all__ = [
    "ApprovalClaims",
    "ApprovalService",
    "ApprovalTokenError",
    "ApprovalTokenService",
    "Horizon",
    "InMemoryNonceStore",
    "NonceStore",
    "Proposal",
    "ProposalStatus",
    "TokenFailure",
    "transition",
]
