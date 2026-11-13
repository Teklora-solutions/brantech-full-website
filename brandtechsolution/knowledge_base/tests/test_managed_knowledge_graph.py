"""Legacy knowledge interface uses managed spaces, not an unversioned vector column."""
from django.test import TestCase
from ai_workflows.harness.memory import Memory
from knowledge_base.models import EmbeddingSpace, EmbeddingWork, KnowledgeDocument, MemoryDocument
from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent
from knowledge_base.tests.test_embedding_lifecycle import FakeEmbedder, ProviderFailure


class ManagedKnowledgeGraphTests(TestCase):
    def setUp(self):
        EmbeddingSpace.objects.filter(status='active').update(status='retired')
        EmbeddingSpace.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=3, status='active')
        self.client_stub = FakeEmbedder()
        self.agent = KnowledgeBaseAgent()
        self.agent.memory = Memory(scope='knowledge_base', embedder=self.client_stub)

    def test_published_article_replay_reuses_document_and_vector(self):
        first = self.agent.index_document('Synthetic article', 'Sanitized content', metadata={'article_id': 42})
        second = self.agent.index_document('Synthetic article', 'Sanitized content', metadata={'article_id': 42})
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(KnowledgeDocument.objects.count(), 1)
        self.assertEqual(MemoryDocument.objects.count(), 1)
        self.assertEqual(len(self.client_stub.calls), 1)
        self.assertIsNone(first.embedding)
        self.assertEqual(self.agent.semantic_search('content')[0].pk, first.pk)
        self.assertEqual(self.agent.search_mode, 'semantic')

    def test_failure_retains_article_and_durable_retry(self):
        self.client_stub.failure = ProviderFailure()
        document = self.agent.index_document('Synthetic article', 'Sanitized content', metadata={'article_id': 42})
        self.assertTrue(KnowledgeDocument.objects.filter(pk=document.pk).exists())
        self.assertEqual(EmbeddingWork.objects.get().status, 'retry')

    def test_unclassified_historical_documents_are_not_resent_or_mixed(self):
        legacy = KnowledgeDocument.objects.create(title='Old article', content='Historical keyword text', doc_type='article')
        results = self.agent.semantic_search('keyword')
        self.assertEqual([row.pk for row in results], [legacy.pk])
        self.assertEqual(self.agent.search_mode, 'semantic_with_legacy_lexical')
        self.assertFalse(MemoryDocument.objects.exists())
        self.assertEqual(self.client_stub.calls, ['keyword'])

    def test_query_failure_exposes_lexical_mode_without_provider_fallback(self):
        legacy = KnowledgeDocument.objects.create(title='Old article', content='Historical keyword text', doc_type='article')
        self.client_stub.failure = ProviderFailure()
        self.assertEqual(self.agent.semantic_search('keyword')[0].pk, legacy.pk)
        self.assertEqual(self.agent.search_mode, 'lexical_fallback')
