"""In-memory test stubs and fixtures for Teklora Document Library.

Provides a self-contained in-memory store and pre-configured role/document
scenarios for unit testing, contract verification, and frontend mock orientation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from .contracts import (
    AccessLevel,
    Audience,
    ChunkContract,
    DocumentContract,
    DocumentVisibility,
    GrantContract,
    ProcessingClearanceRecord,
    ProcessingClearanceState,
    ProcessingState,
    PublicApprovalRecord,
    PublicApprovalState,
    VersionContract,
)


@dataclass
class MockGroup:
    """Mock auth group for testing."""
    id: int
    name: str


@dataclass
class MockUser:
    """Mock user matching Django User interface."""
    id: int
    username: str
    email: str = ""
    is_authenticated: bool = True
    is_active: bool = True
    is_staff: bool = False
    is_superuser: bool = False
    is_anonymous: bool = False
    groups: List[MockGroup] = field(default_factory=list)
    permissions: Set[str] = field(default_factory=set)

    def has_perm(self, perm: str) -> bool:
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        return perm in self.permissions


class InMemoryLibraryStore:
    """In-memory document repository implementing the library contracts."""

    def __init__(self):
        self.documents: Dict[int, DocumentContract] = {}
        self.versions: Dict[int, VersionContract] = {}
        self.grants: Dict[int, List[GrantContract]] = {}  # doc_id -> list[GrantContract]
        self.clearances: Dict[int, ProcessingClearanceRecord] = {}  # ver_id -> record
        self.approvals: Dict[int, PublicApprovalRecord] = {}        # ver_id -> record
        self.chunks: Dict[int, List[ChunkContract]] = {}          # ver_id -> list[ChunkContract]

        self._doc_seq = 1
        self._ver_seq = 1
        self._grant_seq = 1
        self._clearance_seq = 1
        self._approval_seq = 1
        self._chunk_seq = 1

    def create_document(
        self,
        owner_id: int,
        title: str,
        description: str = "",
        category: str = "general",
        tags: Optional[List[str]] = None,
        visibility: DocumentVisibility = DocumentVisibility.PRIVATE,
    ) -> DocumentContract:
        doc = DocumentContract(
            id=self._doc_seq,
            owner_id=owner_id,
            title=title,
            description=description,
            category=category,
            tags=tags or [],
            visibility=visibility,
            is_deleted=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.documents[doc.id] = doc
        self.grants[doc.id] = []
        self._doc_seq += 1
        return doc

    def add_version(
        self,
        document_id: int,
        uploader_id: int,
        original_filename: str,
        storage_key: str,
        detected_format: str,
        size_bytes: int,
        checksum_sha256: str,
        processing_state: ProcessingState = ProcessingState.AWAITING_CLEARANCE,
        clearance_state: ProcessingClearanceState = ProcessingClearanceState.PENDING,
        public_approval_state: PublicApprovalState = PublicApprovalState.NOT_REVIEWED,
    ) -> VersionContract:
        doc = self.documents[document_id]
        ver_num = len([v for v in self.versions.values() if v.document_id == document_id]) + 1
        ver = VersionContract(
            id=self._ver_seq,
            document_id=document_id,
            version_number=ver_num,
            storage_key=storage_key,
            original_filename=original_filename,
            detected_format=detected_format,
            size_bytes=size_bytes,
            checksum_sha256=checksum_sha256,
            processing_state=processing_state,
            clearance_state=clearance_state,
            public_approval_state=public_approval_state,
            uploader_id=uploader_id,
            created_at=datetime.now(timezone.utc),
        )
        self.versions[ver.id] = ver
        self.chunks[ver.id] = []
        doc.current_version_id = ver.id
        self._ver_seq += 1
        return ver

    def add_grant(
        self,
        document_id: int,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        access_level: AccessLevel = AccessLevel.READ,
    ) -> GrantContract:
        grant = GrantContract(
            id=self._grant_seq,
            document_id=document_id,
            user_id=user_id,
            group_id=group_id,
            access_level=access_level,
        )
        self.grants.setdefault(document_id, []).append(grant)
        self._grant_seq += 1
        return grant

    def add_chunk(
        self,
        version_id: int,
        document_id: int,
        ordinal: int,
        text: str,
        page_or_section: str = "",
        content_hash: str = "",
    ) -> ChunkContract:
        chunk = ChunkContract(
            id=self._chunk_seq,
            version_id=version_id,
            document_id=document_id,
            ordinal=ordinal,
            text=text,
            page_or_section=page_or_section,
            content_hash=content_hash,
        )
        self.chunks.setdefault(version_id, []).append(chunk)
        self._chunk_seq += 1
        return chunk

    def clear_processing(
        self,
        version_id: int,
        admin_id: int,
        state: ProcessingClearanceState = ProcessingClearanceState.APPROVED,
        classification: str = "internal_standard",
        reason: str = "",
    ) -> ProcessingClearanceRecord:
        ver = self.versions[version_id]
        ver.clearance_state = state
        if state == ProcessingClearanceState.APPROVED:
            ver.processing_state = ProcessingState.READY
        elif state == ProcessingClearanceState.REJECTED:
            ver.processing_state = ProcessingState.BLOCKED

        rec = ProcessingClearanceRecord(
            id=self._clearance_seq,
            version_id=version_id,
            state=state,
            classification=classification,
            permitted_provider="gemini",
            reviewer_id=admin_id,
            reviewed_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self.clearances[version_id] = rec
        self._clearance_seq += 1
        return rec

    def set_public_approval(
        self,
        version_id: int,
        admin_id: int,
        state: PublicApprovalState = PublicApprovalState.APPROVED,
        reason: str = "",
    ) -> PublicApprovalRecord:
        ver = self.versions[version_id]
        ver.public_approval_state = state
        rec = PublicApprovalRecord(
            id=self._approval_seq,
            version_id=version_id,
            state=state,
            reviewer_id=admin_id,
            reviewed_at=datetime.now(timezone.utc),
            reason=reason,
        )
        self.approvals[version_id] = rec
        self._approval_seq += 1
        return rec

    def soft_delete(self, document_id: int) -> None:
        if document_id in self.documents:
            self.documents[document_id].is_deleted = True

    def get_document(self, document_id: int) -> Optional[DocumentContract]:
        return self.documents.get(document_id)

    def get_version(self, version_id: int) -> Optional[VersionContract]:
        return self.versions.get(version_id)

    def get_grants(self, document_id: int) -> List[GrantContract]:
        return self.grants.get(document_id, [])

    def list_chunks(self) -> List[ChunkContract]:
        all_chunks: List[ChunkContract] = []
        for chunk_list in self.chunks.values():
            all_chunks.extend(chunk_list)
        return all_chunks


def create_test_scenarios() -> Dict[str, Any]:
    """Build a comprehensive, pre-wired suite of test actors and documents."""
    store = InMemoryLibraryStore()

    # Groups
    admin_group = MockGroup(id=1, name="Administrator")
    research_group = MockGroup(id=2, name="Research Team")

    # Users
    owner = MockUser(id=1, username="owner", is_staff=True)
    admin = MockUser(
        id=2,
        username="admin",
        is_staff=True,
        groups=[admin_group],
        permissions={"staff.approve_library_publication", "staff.manage_staff"},
    )
    superuser = MockUser(id=99, username="super", is_staff=True, is_superuser=True)
    reader_user = MockUser(id=3, username="reader", is_staff=True)
    editor_user = MockUser(id=4, username="editor", is_staff=True)
    group_member = MockUser(id=5, username="researcher", is_staff=True, groups=[research_group])
    org_staff = MockUser(id=6, username="colleague", is_staff=True)
    deactivated = MockUser(id=7, username="former_staff", is_active=False, is_staff=True)
    anonymous = MockUser(id=0, username="anonymous", is_authenticated=False, is_anonymous=True)
    unrelated_external = MockUser(id=8, username="external_signup", is_staff=False)

    # 1. Private Document (Uncleared upon upload)
    doc_private = store.create_document(
        owner_id=owner.id,
        title="2026 Strategic Advisory Notes",
        description="Confidential operational planning notes.",
        visibility=DocumentVisibility.PRIVATE,
    )
    ver_private = store.add_version(
        document_id=doc_private.id,
        uploader_id=owner.id,
        original_filename="strategy-2026.docx",
        storage_key="library/private/strategy-2026.docx",
        detected_format="docx",
        size_bytes=1024 * 1024,
        checksum_sha256="abc123sha",
        processing_state=ProcessingState.AWAITING_CLEARANCE,
        clearance_state=ProcessingClearanceState.PENDING,
        public_approval_state=PublicApprovalState.NOT_REVIEWED,
    )
    store.add_chunk(
        version_id=ver_private.id,
        document_id=doc_private.id,
        ordinal=0,
        text="Executive strategic roadmap for 2026 expansion in East Africa.",
        page_or_section="Section 1.1",
        content_hash="hash_p1",
    )

    # 2. Cleared Internal Document (with direct grants)
    doc_granted = store.create_document(
        owner_id=owner.id,
        title="API Architecture Design Document",
        description="Architecture specification for microservices.",
        visibility=DocumentVisibility.PRIVATE,
    )
    ver_granted = store.add_version(
        document_id=doc_granted.id,
        uploader_id=owner.id,
        original_filename="arch-spec.pdf",
        storage_key="library/private/arch-spec.pdf",
        detected_format="pdf",
        size_bytes=2 * 1024 * 1024,
        checksum_sha256="def456sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.NOT_REVIEWED,
    )
    store.add_grant(doc_granted.id, user_id=reader_user.id, access_level=AccessLevel.READ)
    store.add_grant(doc_granted.id, user_id=editor_user.id, access_level=AccessLevel.EDIT)
    store.add_chunk(
        version_id=ver_granted.id,
        document_id=doc_granted.id,
        ordinal=0,
        text="The API uses JSON-RPC over stdio and stateless token authorization.",
        page_or_section="Page 3",
        content_hash="hash_g1",
    )

    # 3. Group-Shared Document
    doc_group = store.create_document(
        owner_id=owner.id,
        title="Biometric Lab Research Findings",
        description="Research notes for the science team.",
        visibility=DocumentVisibility.PRIVATE,
    )
    ver_group = store.add_version(
        document_id=doc_group.id,
        uploader_id=owner.id,
        original_filename="lab-report.pdf",
        storage_key="library/private/lab-report.pdf",
        detected_format="pdf",
        size_bytes=5 * 1024 * 1024,
        checksum_sha256="group789sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.NOT_REVIEWED,
    )
    store.add_grant(doc_group.id, group_id=research_group.id, access_level=AccessLevel.READ)
    store.add_chunk(
        version_id=ver_group.id,
        document_id=doc_group.id,
        ordinal=0,
        text="Experimental results verify high accuracy under ambient lighting.",
        page_or_section="Page 12",
        content_hash="hash_grp1",
    )

    # 4. Organisation-Shared Document
    doc_org = store.create_document(
        owner_id=owner.id,
        title="Employee Handbook and Code of Conduct",
        description="Company policies applicable to all staff.",
        visibility=DocumentVisibility.ORGANISATION,
    )
    ver_org = store.add_version(
        document_id=doc_org.id,
        uploader_id=owner.id,
        original_filename="handbook.md",
        storage_key="library/org/handbook.md",
        detected_format="md",
        size_bytes=50 * 1024,
        checksum_sha256="org000sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.NOT_REVIEWED,
    )
    store.add_chunk(
        version_id=ver_org.id,
        document_id=doc_org.id,
        ordinal=0,
        text="All employees must adhere to professional ethics and KDPA compliance.",
        page_or_section="Section 2",
        content_hash="hash_org1",
    )

    # 5. Public-Approved Document
    doc_public = store.create_document(
        owner_id=owner.id,
        title="Teklora Public Whitepaper on AI Governance",
        description="Official publication on enterprise agent architectures.",
        visibility=DocumentVisibility.PRIVATE,
    )
    ver_public = store.add_version(
        document_id=doc_public.id,
        uploader_id=owner.id,
        original_filename="ai-whitepaper.pdf",
        storage_key="library/public/ai-whitepaper.pdf",
        detected_format="pdf",
        size_bytes=4 * 1024 * 1024,
        checksum_sha256="pub111sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.APPROVED,
    )
    store.add_chunk(
        version_id=ver_public.id,
        document_id=doc_public.id,
        ordinal=0,
        text="Enterprise AI requires strict verification boundaries and zero unauthorized provider calls.",
        page_or_section="Executive Summary",
        content_hash="hash_pub1",
    )

    # 6. Revoked Public Document
    doc_revoked = store.create_document(
        owner_id=owner.id,
        title="Deprecated Press Release 2025",
        description="Outdated announcement.",
        visibility=DocumentVisibility.PRIVATE,
    )
    ver_revoked = store.add_version(
        document_id=doc_revoked.id,
        uploader_id=owner.id,
        original_filename="press-release.txt",
        storage_key="library/public/press-release.txt",
        detected_format="txt",
        size_bytes=10 * 1024,
        checksum_sha256="rev222sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.REVOKED,
    )
    store.add_chunk(
        version_id=ver_revoked.id,
        document_id=doc_revoked.id,
        ordinal=0,
        text="Historical announcement that has been officially retracted.",
        page_or_section="Body",
        content_hash="hash_rev1",
    )

    # 7. Deleted Document
    doc_deleted = store.create_document(
        owner_id=owner.id,
        title="Obsolete Scrapped Specification",
        description="Draft deleted by owner.",
        visibility=DocumentVisibility.PRIVATE,
    )
    store.add_version(
        document_id=doc_deleted.id,
        uploader_id=owner.id,
        original_filename="obsolete.md",
        storage_key="library/trash/obsolete.md",
        detected_format="md",
        size_bytes=5 * 1024,
        checksum_sha256="del333sha",
        processing_state=ProcessingState.READY,
        clearance_state=ProcessingClearanceState.APPROVED,
        public_approval_state=PublicApprovalState.APPROVED,
    )
    store.soft_delete(doc_deleted.id)

    return {
        "store": store,
        "actors": {
            "owner": owner,
            "admin": admin,
            "superuser": superuser,
            "reader_user": reader_user,
            "editor_user": editor_user,
            "group_member": group_member,
            "org_staff": org_staff,
            "deactivated": deactivated,
            "anonymous": anonymous,
            "unrelated_external": unrelated_external,
        },
        "docs": {
            "private": doc_private,
            "granted": doc_granted,
            "group": doc_group,
            "org": doc_org,
            "public": doc_public,
            "revoked": doc_revoked,
            "deleted": doc_deleted,
        },
        "versions": {
            "private": ver_private,
            "granted": ver_granted,
            "group": ver_group,
            "org": ver_org,
            "public": ver_public,
            "revoked": ver_revoked,
        },
    }
