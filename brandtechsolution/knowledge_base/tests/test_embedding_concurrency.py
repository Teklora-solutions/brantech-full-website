"""Real PostgreSQL transactions/connections, not simulated row locking."""
import threading
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from knowledge_base import embedding_lifecycle as lifecycle
from knowledge_base.models import Embedding, EmbeddingSpace, MemoryDocument
from knowledge_base.tests.test_embedding_lifecycle import FakeEmbedder


class EmbeddingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        EmbeddingSpace.objects.filter(status='active').update(status='retired')
        self.space = EmbeddingSpace.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=3, status='active')

    def test_competing_workers_claim_only_one_paid_call(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL transaction locks required')
        record = MemoryDocument.objects.create(scope='site', text='Sanitized fixture', content_hash='hash')
        work = lifecycle.ensure_work(record, self.space)
        entered, release = threading.Event(), threading.Event()
        client = FakeEmbedder()
        original = client.embed_query
        errors, result = [], []
        def slow_call(text, output_dimensionality=None):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Test barrier timed out')
            return original(text, output_dimensionality)
        client.embed_query = slow_call
        def worker():
            close_old_connections()
            try:
                result.append(lifecycle.perform_work(work.pk, embedder=client))
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                close_old_connections()
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            self.assertTrue(entered.wait(10))
            self.assertFalse(lifecycle.perform_work(work.pk, embedder=FakeEmbedder()))
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result, [True])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(Embedding.objects.filter(document=record, space=self.space).count(), 1)

    def test_concurrent_admin_requests_cannot_start_two_migrations(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL transaction locks required')
        admin = get_user_model().objects.create_superuser('concurrent-embedding-admin', 'synthetic@example.test', 'unused')
        barrier = threading.Barrier(2)
        result, errors = [], []
        def start():
            close_old_connections()
            try:
                barrier.wait(10)
                lifecycle.start_migration(admin, model='gemini-embedding-2', backend='vertex', dimensions=768)
                result.append('created')
            except ValidationError:
                result.append('refused')
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                close_old_connections()
        threads = [threading.Thread(target=start, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertCountEqual(result, ['created', 'refused'])
