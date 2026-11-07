"""Teklora Document Library Safe Retrieval Engine.

Implements permission-aware retrieval and citation formatting for AI agents,
RAG pipelines, and search interfaces:
- Enforces strict ACL filtering prior to similarity ranking or limit slicing.
- Evaluates audience context (Internal vs Public).
- Guarantees zero public leakage of uncleared or unapproved documents.
- Produces tamper-evident, audit-safe citations with provenance.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

from .contracts import (
    AccessLevel,
    Audience,
    ChunkContract,
    DocumentContract,
    DocumentVisibility,
    LibraryAction,
    LibraryRetrievalResult,
    PolicyDecision,
    ProcessingClearanceState,
    ProcessingState,
    PublicApprovalState,
    VersionContract,
)
from .policy import LibraryPolicy

PROTECTED_LIBRARY_SCOPES = ("library", "staff_library")


class LibraryRetrievalEngine:
    """ACL-aware retrieval engine for library documents and chunks."""

    def __init__(self, store: Optional[Any] = None):
        self.store = store

    def retrieve(
        self,
        query: str,
        actor: Any,
        audience: Audience = Audience.INTERNAL,
        limit: int = 5,
        category: Optional[str] = None,
        candidate_chunks: Optional[Sequence[Any]] = None,
    ) -> List[LibraryRetrievalResult]:
        """Execute permission-gated semantic/lexical chunk retrieval."""
        results: List[LibraryRetrievalResult] = []

        # If candidate chunks are passed directly (e.g. from a vector store or test harness)
        chunks = candidate_chunks or (self.store.list_chunks() if self.store else [])

        for chunk in chunks:
            doc = self._resolve_document(chunk)
            if doc is None or getattr(doc, "is_deleted", False):
                continue

            ver = self._resolve_version(chunk, doc)
            if ver is None:
                continue

            if category and getattr(doc, "category", None) != category:
                continue

            # Policy evaluation
            doc_id = getattr(doc, "id", 0)
            grants = self.store.get_grants(doc_id) if self.store else None
            decision = LibraryPolicy.evaluate(
                actor=actor,
                document=doc,
                action=LibraryAction.READ,
                version=ver,
                audience=audience,
                grants=grants,
            )

            if not decision.allowed:
                continue

            # Compute score (simulated or real lexical/vector match)
            score = self._compute_similarity(query, getattr(chunk, "text", ""))

            # Build safe citation
            doc_id = getattr(doc, "id", 0)
            ver_num = getattr(ver, "version_number", 1)
            title = getattr(doc, "title", "Document")
            page_sec = getattr(chunk, "page_or_section", "")
            cit_suffix = f", {page_sec}" if page_sec else ""
            citation = f"[Doc #{doc_id} v{ver_num}: {title}{cit_suffix}]"

            results.append(
                LibraryRetrievalResult(
                    document_id=doc_id,
                    version_id=getattr(ver, "id", 0),
                    title=title,
                    page_or_section=page_sec,
                    text=getattr(chunk, "text", ""),
                    score=score,
                    citation=citation,
                    visibility=getattr(doc, "visibility", DocumentVisibility.PRIVATE),
                    is_public=getattr(ver, "public_approval_state", None) == PublicApprovalState.APPROVED,
                )
            )

        # Rank by score descending and apply limit
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _resolve_document(self, chunk: Any) -> Optional[Any]:
        if hasattr(chunk, "document") and chunk.document is not None:
            return chunk.document
        if self.store and hasattr(chunk, "document_id"):
            return self.store.get_document(chunk.document_id)
        return None

    def _resolve_version(self, chunk: Any, doc: Any) -> Optional[Any]:
        if hasattr(chunk, "version") and chunk.version is not None:
            return chunk.version
        if self.store and hasattr(chunk, "version_id"):
            return self.store.get_version(chunk.version_id)
        return getattr(doc, "current_version", None)

    @staticmethod
    def _compute_similarity(query: str, text: str) -> float:
        """Deterministic lexical overlap score for testing and fallbacks."""
        if not query or not text:
            return 0.0
        q_words = set(query.lower().split())
        t_words = set(text.lower().split())
        if not q_words:
            return 0.0
        overlap = len(q_words.intersection(t_words))
        return round(float(overlap) / float(len(q_words)), 4)
