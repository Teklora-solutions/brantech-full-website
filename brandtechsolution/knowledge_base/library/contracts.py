"""Teklora Document Library Contracts and Interface Specifications.

Canonical definitions for document library entities, access control levels,
processing states, clearance lifecycles, and policy evaluation results.
These contracts form the foundation for Task #33 (ACL & Retrieval Foundation)
and provide the agreed schema for Junior (LIB-02/03 backend) and jmunuve/Emmanuel (LIB-05/06 UI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set


class Audience(str, Enum):
    """Retrieval audience context."""
    INTERNAL = "internal"  # Staff, internal agents, or authenticated team workflows
    PUBLIC = "public"      # Website visitors, public search, or anonymous AI agents


class DocumentVisibility(str, Enum):
    """Document visibility scope."""
    PRIVATE = "private"            # Private to owner and explicitly granted subjects
    ORGANISATION = "organisation"  # Accessible to all active authenticated staff members


class AccessLevel(str, Enum):
    """Level of access granted to a user or group."""
    READ = "read"  # View metadata, view chunks/extracted text, download original
    EDIT = "edit"  # Edit metadata, upload new versions (does not grant sharing or deletion)


class ProcessingClearanceState(str, Enum):
    """State of administrator clearance for external processing (OCR/embeddings/AI)."""
    PENDING = "pending"    # Awaiting administrator review
    APPROVED = "approved"  # Administrator explicitly permitted external processing
    REJECTED = "rejected"  # Administrator blocked external processing


class ProcessingState(str, Enum):
    """Lifecycle state of document text extraction and vector embedding."""
    AWAITING_CLEARANCE = "awaiting_clearance"  # Quarantined; no external provider calls
    QUEUED = "queued"                          # Clearance granted, queued for worker
    PROCESSING = "processing"                  # Extraction/OCR/embedding in progress
    READY = "ready"                            # Extraction and embedding completed successfully
    FAILED = "failed"                          # Extraction or embedding encountered an error
    BLOCKED = "blocked"                        # Blocked due to policy or restricted data


class PublicApprovalState(str, Enum):
    """State of administrator publication approval for public retrieval."""
    NOT_REVIEWED = "not_reviewed"  # Initial state upon version creation
    PENDING = "pending"            # Public review requested
    APPROVED = "approved"          # Administrator approved for public retrieval
    REJECTED = "rejected"          # Administrator rejected public use
    REVOKED = "revoked"            # Previously approved, subsequently revoked


class LibraryAction(str, Enum):
    """Actions subject to policy evaluation."""
    READ = "read"                      # Read metadata, chunk text, or search snippet
    DOWNLOAD = "download"              # Stream or download original stored file
    EDIT = "edit"                      # Update document title/desc or upload new version
    SHARE = "share"                    # Modify grants or toggle organisation visibility
    CLEAR_PROCESSING = "clear_processing"  # Administrator approve/reject external processing
    APPROVE_PUBLIC = "approve_public"  # Administrator approve public retrieval
    REVOKE_PUBLIC = "revoke_public"    # Administrator revoke public retrieval
    DELETE = "delete"                  # Soft-delete document


@dataclass(frozen=True)
class PolicyDecision:
    """Result of an access control evaluation."""
    allowed: bool
    code: str
    reason: str

    @classmethod
    def allow(cls, code: str = "ALLOWED", reason: str = "Access granted") -> "PolicyDecision":
        return cls(allowed=True, code=code, reason=reason)

    @classmethod
    def deny(cls, code: str, reason: str) -> "PolicyDecision":
        return cls(allowed=False, code=code, reason=reason)

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class DocumentContract:
    """Document metadata contract."""
    id: int
    owner_id: int
    title: str
    description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    visibility: DocumentVisibility = DocumentVisibility.PRIVATE
    is_deleted: bool = False
    current_version_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class VersionContract:
    """Document version and storage contract."""
    id: int
    document_id: int
    version_number: int
    storage_key: str
    original_filename: str
    detected_format: str  # "pdf", "docx", "txt", "md", "png", "jpeg"
    size_bytes: int
    checksum_sha256: str
    processing_state: ProcessingState = ProcessingState.AWAITING_CLEARANCE
    clearance_state: ProcessingClearanceState = ProcessingClearanceState.PENDING
    public_approval_state: PublicApprovalState = PublicApprovalState.NOT_REVIEWED
    safe_error_code: str = ""
    uploader_id: int = 0
    created_at: Optional[datetime] = None


@dataclass
class GrantContract:
    """Explicit access grant to a user or group."""
    id: int
    document_id: int
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    access_level: AccessLevel = AccessLevel.READ


@dataclass
class ProcessingClearanceRecord:
    """Administrator external processing clearance decision."""
    id: int
    version_id: int
    state: ProcessingClearanceState
    classification: str = "internal_standard"
    permitted_provider: str = "gemini"
    reviewer_id: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    reason: str = ""


@dataclass
class PublicApprovalRecord:
    """Administrator public retrieval publication decision."""
    id: int
    version_id: int
    state: PublicApprovalState
    requester_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    requested_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reason: str = ""


@dataclass
class ChunkContract:
    """Extracted text chunk with provenance for semantic search and RAG."""
    id: int
    version_id: int
    document_id: int
    ordinal: int
    text: str
    page_or_section: str = ""
    content_hash: str = ""
    memory_document_id: Optional[int] = None


@dataclass
class LibraryRetrievalResult:
    """Sanitized retrieval result with audit-safe citation."""
    document_id: int
    version_id: int
    title: str
    page_or_section: str
    text: str
    score: float
    citation: str
    visibility: DocumentVisibility
    is_public: bool
