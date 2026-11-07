"""Teklora Document Library & ACL Package.

Exports contracts, policy evaluator, safe retrieval engine, and test stubs.
"""

from .contracts import (
    AccessLevel,
    Audience,
    ChunkContract,
    DocumentContract,
    DocumentVisibility,
    GrantContract,
    LibraryAction,
    LibraryRetrievalResult,
    PolicyDecision,
    ProcessingClearanceRecord,
    ProcessingClearanceState,
    ProcessingState,
    PublicApprovalRecord,
    PublicApprovalState,
    VersionContract,
)
from .policy import (
    ADMIN_CAPABILITY,
    ADMIN_GROUP_NAME,
    LibraryPolicy,
)
from .retrieval import (
    PROTECTED_LIBRARY_SCOPES,
    LibraryRetrievalEngine,
)
from .stubs import (
    InMemoryLibraryStore,
    MockGroup,
    MockUser,
    create_test_scenarios,
)

__all__ = [
    "AccessLevel",
    "Audience",
    "ChunkContract",
    "DocumentContract",
    "DocumentVisibility",
    "GrantContract",
    "LibraryAction",
    "LibraryRetrievalResult",
    "PolicyDecision",
    "ProcessingClearanceRecord",
    "ProcessingClearanceState",
    "ProcessingState",
    "PublicApprovalRecord",
    "PublicApprovalState",
    "VersionContract",
    "ADMIN_CAPABILITY",
    "ADMIN_GROUP_NAME",
    "LibraryPolicy",
    "PROTECTED_LIBRARY_SCOPES",
    "LibraryRetrievalEngine",
    "InMemoryLibraryStore",
    "MockGroup",
    "MockUser",
    "create_test_scenarios",
]
