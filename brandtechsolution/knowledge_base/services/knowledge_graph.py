"""
Module 13: Knowledge Base Agent

Indexes all articles, research papers, trends, and verified facts into a vector store
with pgvector embeddings. Enables semantic search and cross-referencing for all agents.
"""
import logging
from typing import List, Dict, Any

from ai_workflows.harness.errors import MemoryUnavailable
from ai_workflows.harness.memory import Memory
from knowledge_base.models import KnowledgeDocument

logger = logging.getLogger(__name__)


class KnowledgeBaseAgent:
    """Manages long-term semantic knowledge memory for Teklora."""

    def __init__(self):
        self.memory = Memory(scope='knowledge_base')
        self.search_mode = 'semantic'

    def index_document(self, title: str, content: str, doc_type: str = 'article', metadata: Dict[str, Any] = None) -> KnowledgeDocument:
        """Generates embedding vector and stores document in Knowledge Base."""
        metadata = metadata or {}
        from knowledge_base.embedding_lifecycle import source_fence
        with source_fence():
            article_id = metadata.get('article_id')
            doc = KnowledgeDocument.objects.filter(doc_type=doc_type, metadata__article_id=article_id).first() if article_id is not None else None
            if doc is None:
                doc = KnowledgeDocument.objects.create(title=title, doc_type=doc_type, content=content, metadata=metadata)
            else:
                doc.title, doc.content, doc.metadata = title, content, metadata
                doc.save(update_fields=['title', 'content', 'metadata'])
        try:
            # Preserve the old bounded source excerpt, but use model-specific,
            # resumable spaces instead of an unversioned 3072-wide column.
            self.memory.remember(content[:3000], title=title, kind='knowledge_document', obj=doc, metadata=metadata or {})
        except MemoryUnavailable:
            logger.warning('Knowledge document retained for automatic embedding recovery: document=%s', doc.pk)
        return doc

    def semantic_search(self, query: str, limit: int = 5) -> List[KnowledgeDocument]:
        """Performs pgvector cosine distance search across Knowledge Base documents."""
        try:
            records = self.memory.recall(query, kind='knowledge_document', limit=limit)
            ids = [record.document.object_id for record in records]
            documents = KnowledgeDocument.objects.in_bulk(ids)
            results = [documents[pk] for pk in ids if pk in documents]
            # Unversioned historical vectors have no trustworthy model/profile
            # provenance. Keep their documents discoverable lexically without
            # mixing spaces or silently sending old, unclassified text to Google.
            from django.contrib.contenttypes.models import ContentType
            from knowledge_base.models import MemoryDocument
            managed = MemoryDocument.objects.filter(scope='knowledge_base', kind='knowledge_document',
                content_type=ContentType.objects.get_for_model(KnowledgeDocument)).values('object_id')
            legacy = KnowledgeDocument.objects.exclude(pk__in=managed)
            if legacy.exists():
                self.search_mode = 'semantic_with_legacy_lexical'
                results.extend(legacy.filter(content__icontains=query)[:max(0, limit-len(results))])
            return results
        except MemoryUnavailable:
            # The caller exposes this mode; never pretend a lexical fallback
            # is a successful vector search, or fall back to another model.
            self.search_mode = 'lexical_fallback'
            logger.warning('Knowledge search using explicit lexical fallback')
            return list(KnowledgeDocument.objects.filter(content__icontains=query)[:limit])
