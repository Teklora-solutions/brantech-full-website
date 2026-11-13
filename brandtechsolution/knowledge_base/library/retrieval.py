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
        if self.store is None and candidate_chunks is None:
            return self._retrieve_database(query, actor, audience, limit, category)

        # Explicit test/store adapters still pass through the same policy.
        chunks = candidate_chunks if candidate_chunks is not None else (self.store.list_chunks() if self.store else [])

        for chunk in chunks:
            doc = self._resolve_document(chunk)
            if doc is None or getattr(doc, "is_deleted", False):
                continue

            ver = self._resolve_version(chunk, doc)
            if ver is None:
                continue
            if getattr(doc, 'current_version_id', None) != getattr(ver, 'id', None):
                continue
            if getattr(ver, 'processing_state', None) != ProcessingState.READY:
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

    def _retrieve_database(self, query, actor, audience, limit, category):
        """Lexical retrieval with ACL/state joins before ranking, no egress or cache."""
        from .access import eligible_chunks
        if not query.strip():
            return []
        if actor is not None and getattr(actor, 'is_authenticated', False) and not actor.is_active:
            return []
        rows = eligible_chunks(actor, public=audience == Audience.PUBLIC)
        if category:
            rows = rows.filter(version__document__category=category)
        # Narrow candidates in SQL first; never load an inaccessible chunk.
        from django.db.models import Q
        predicate = Q()
        for word in query.split()[:20]:
            predicate |= Q(text__icontains=word)
        rows = rows.filter(predicate)
        def candidates():
            for chunk in rows.iterator():
                version = chunk.version
                doc = version.document
                yield LibraryRetrievalResult(
                    document_id=doc.pk, version_id=version.pk, title=doc.title,
                    page_or_section=chunk.page_or_section, text=chunk.text,
                    score=self._compute_similarity(query, chunk.text),
                    citation=f'[Doc #{doc.pk} v{version.version_number}: {doc.title}, {chunk.page_or_section}]',
                    visibility=doc.visibility, is_public=version.public_approval_state == 'approved',
                )
        import heapq
        selected = heapq.nlargest(max(0, min(int(limit), 20)), candidates(), key=lambda item: item.score)
        self._audit_admin_results(actor, selected)
        return selected

    def retrieve_semantic(self, query, actor=None, *, audience=Audience.INTERNAL, limit=5, embedder=None):
        """Rank only eligible joined chunks in the current embedding space.

        No generic Memory.recall call: scope strings cannot authorize retrieval.
        Callers may explicitly choose lexical `retrieve` when semantic memory is down.
        """
        from pgvector.django import CosineDistance
        from ai_workflows.harness.memory import Memory
        from knowledge_base.models import EmbeddingSpace
        from .access import eligible_chunks
        from langsmith import tracing_context
        if not query.strip():
            return []
        authenticated = actor is not None and getattr(actor, 'is_authenticated', False)
        def refreshed_actor():
            if not authenticated:
                return actor
            from django.contrib.auth import get_user_model
            users = get_user_model().objects.filter(pk=actor.pk, is_active=True)
            if audience != Audience.PUBLIC:
                users = users.filter(is_staff=True)
            return users.first()
        current_actor = refreshed_actor()
        if authenticated and current_actor is None:
            return []
        rows = eligible_chunks(current_actor, public=audience == Audience.PUBLIC)
        if not rows.exists():
            return []
        space = EmbeddingSpace.active()
        if not space:
            from ai_workflows.harness.errors import MemoryUnavailable
            raise MemoryUnavailable('Library semantic search has no active embedding space.')
        if space.provider != 'gemini':
            from ai_workflows.harness.errors import MemoryUnavailable
            raise MemoryUnavailable('Library embedding provider is not cleared.')
        # Query text is user-supplied; no document text is sent to the embedder.
        with tracing_context(enabled=False):
            vector = Memory(embedder=embedder)._embed(query, space)
        # Credential refresh/query generation may be slow: rebuild permissions
        # from a fresh user after it, including removed administrator roles.
        current_actor = refreshed_actor()
        if authenticated and current_actor is None:
            return []
        rows = eligible_chunks(current_actor, public=audience == Audience.PUBLIC)
        from knowledge_base.embedding_lifecycle import current_vectors, verified_library_chunks
        rows = rows.filter(pk__in=verified_library_chunks().values('pk'), memory_document__embeddings__space=space,
                           memory_document__embeddings__pk__in=current_vectors(space).values('pk')).annotate(
            distance=CosineDistance('memory_document__embeddings__vector', vector),
        ).order_by('distance')[:max(0, min(int(limit), 20))]
        results = []
        for chunk in rows:
            version, document = chunk.version, chunk.version.document
            results.append(LibraryRetrievalResult(
                document_id=document.pk, version_id=version.pk, title=document.title,
                page_or_section=chunk.page_or_section, text=chunk.text,
                score=1.0 - float(chunk.distance),
                citation=f'[Doc #{document.pk} v{version.version_number}: {document.title}, {chunk.page_or_section}]',
                visibility=document.visibility, is_public=version.public_approval_state == 'approved',
            ))
        self._audit_admin_results(current_actor, results)
        return results

    @staticmethod
    def _audit_admin_results(actor, results):
        if actor is None or not LibraryPolicy.is_administrator(actor):
            return
        from knowledge_base.models import LibraryAudit
        LibraryAudit.objects.bulk_create([
            LibraryAudit(document_id=doc_id, version_id=version_id, actor=actor, action='admin_retrieve')
            for doc_id, version_id in {(item.document_id, item.version_id) for item in results}
        ])

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
