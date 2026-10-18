"""Trade proposals, lifecycle and approval tokens (BR-002, BR-003, FR-011, FR-023, FR-024).

Must not import signals/forecasting/astrology: execution depends on this package and RULE-013 keeps
execution isolated from analysis.
"""

from aqta.proposals.lifecycle import (
    ApprovalService,
    Horizon,
    Proposal,
    ProposalStatus,
    resized,
    transition,
    validity_seconds,
)
from aqta.proposals.service import (
    ApprovalRecord,
    InMemoryProposalRepository,
    ProposalRepository,
    ProposalService,
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
    "ApprovalRecord",
    "ApprovalService",
    "ApprovalTokenError",
    "ApprovalTokenService",
    "Horizon",
    "InMemoryNonceStore",
    "InMemoryProposalRepository",
    "NonceStore",
    "Proposal",
    "ProposalRepository",
    "ProposalService",
    "ProposalStatus",
    "TokenFailure",
    "resized",
    "transition",
    "validity_seconds",
]
