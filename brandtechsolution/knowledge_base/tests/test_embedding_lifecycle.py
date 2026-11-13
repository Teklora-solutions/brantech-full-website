"""Offline lifecycle tests: real ORM/ACLs, deterministic provider responses."""
import tempfile
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ai_workflows.harness.errors import MemoryUnavailable
from ai_workflows.harness.memory import Memory
from knowledge_base import embedding_lifecycle as lifecycle
from knowledge_base.models import Embedding, EmbeddingSpace, EmbeddingWork, EmbeddingMigration, LibraryAudit, MemoryDocument
from knowledge_base.library.services import upload_document, mutate
from knowledge_base.tasks import process_version, maintain_embeddings


class FakeEmbedder:
    def __init__(self):
        self.calls = []
        self.failure = None

    def embed_query(self, text, output_dimensionality=None):
        self.calls.append(text)
        if self.failure:
            raise self.failure
        return [1.0] + [0.0] * ((output_dimensionality or 3)-1)

    def embed_documents(self, texts, output_dimensionality=None):
        return [self.embed_query(text, output_dimensionality) for text in texts]


class ProviderFailure(Exception):
    def __init__(self, code=503):
        super().__init__('PRIVATE provider body and credential must not be stored')
        self.code = code


class LifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('embedding-admin', 'embedding@example.test', 'unused')
        cls.staff = User.objects.create_user('embedding-reader', is_staff=True)
        EmbeddingSpace.objects.filter(status='active').update(status='retired')
        cls.active = EmbeddingSpace.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=3, status='active')

    def setUp(self):
        self.fake = FakeEmbedder()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(LIBRARY_STORAGE_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def source(self, text='Sanitized source'):
        return Memory(scope='site', embedder=self.fake).remember(text, title='Synthetic article').document

    def migration(self, auto_activate=False):
        migration = lifecycle.start_migration(self.admin, model='gemini-embedding-2', backend='vertex', dimensions=768, auto_activate=auto_activate)
        self.assertTrue(lifecycle.preflight(migration, embedder=self.fake))
        return migration

    def library(self):
        document = upload_document(self.staff, SimpleUploadedFile('fixture.txt', b'Sanitized library fixture'), title='Fixture', authority=True)
        mutate(self.admin, document.pk, document.current_version_id, 'clear', data={'classification': 'internal_standard', 'reason': 'Synthetic fixture cleared'})
        return document

    def due(self, work):
        EmbeddingWork.objects.filter(pk=work.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        EmbeddingSpace.objects.filter(pk=work.space_id).update(retry_after=None)

    def test_successful_vector_is_not_paid_for_again(self):
        record = self.source()
        work = EmbeddingWork.objects.get(document=record, space=self.active)
        count = len(self.fake.calls)
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertEqual(len(self.fake.calls), count)
        self.assertEqual(Embedding.objects.filter(document=record, space=self.active).count(), 1)

    def test_failed_memory_write_retains_source_for_recovery(self):
        self.fake.failure = ProviderFailure()
        with self.assertRaises(MemoryUnavailable):
            self.source()
        record = MemoryDocument.objects.get(scope='site')
        work = EmbeddingWork.objects.get(document=record)
        self.assertEqual(work.status, 'retry')
        self.assertEqual(work.error_code, 'PROVIDER_UNAVAILABLE')
        self.assertNotIn('PRIVATE', work.error_code)
        self.fake.failure = None
        self.due(work)
        self.assertTrue(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertTrue(Embedding.objects.filter(document=record, content_hash=record.content_hash).exists())

    def test_permanent_credentials_failure_pauses_profile_without_flooding(self):
        self.fake.failure = ProviderFailure(403)
        with self.assertRaises(MemoryUnavailable):
            self.source()
        self.active.refresh_from_db()
        self.assertTrue(self.active.needs_attention)
        record = MemoryDocument.objects.create(text='Other synthetic source', scope='site', content_hash='other')
        work = lifecycle.ensure_work(record, self.active)
        count = len(self.fake.calls)
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertEqual(len(self.fake.calls), count)

    def test_one_invalid_source_does_not_pause_all_sources(self):
        self.fake.failure = ProviderFailure(400)
        with self.assertRaises(MemoryUnavailable):
            self.source()
        self.active.refresh_from_db()
        self.assertFalse(self.active.needs_attention)
        self.assertEqual(EmbeddingWork.objects.get().status, 'blocked')

    def test_profile_identity_cannot_be_edited_in_place(self):
        self.active.model_id = 'gemini-embedding-2'
        with self.assertRaises(ValidationError):
            self.active.save()

    def test_candidate_must_pass_fixed_text_preflight_before_private_calls(self):
        record = self.source()
        migration = lifecycle.start_migration(self.admin, model='gemini-embedding-2', backend='vertex', dimensions=768)
        work = lifecycle.ensure_work(record, migration.target)
        count = len(self.fake.calls)
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertEqual(len(self.fake.calls), count)
        self.assertTrue(lifecycle.preflight(migration, embedder=self.fake))
        self.assertEqual(self.fake.calls[-1], 'Semantic index health check')
        self.assertTrue(lifecycle.perform_work(work.pk, embedder=self.fake))

    def test_failed_preflight_never_dispatches_corpus(self):
        self.source()
        migration = lifecycle.start_migration(self.admin, model='gemini-embedding-2', backend='vertex', dimensions=768)
        self.fake.failure = ProviderFailure(404)
        self.assertFalse(lifecycle.preflight(migration, embedder=self.fake))
        lifecycle.tick(dispatch=False, validate=False)
        self.assertFalse(EmbeddingWork.objects.filter(space=migration.target).exists())
        migration.refresh_from_db()
        self.assertEqual(migration.status, 'blocked')
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)

    def test_candidate_build_keeps_old_vectors_serving(self):
        record = self.source()
        migration = self.migration()
        work = lifecycle.ensure_work(record, migration.target)
        self.assertTrue(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertEqual(Embedding.objects.filter(document=record).count(), 2)
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)

    def test_pause_prevents_new_provider_calls_and_resume_keeps_progress(self):
        record = self.source()
        migration = self.migration()
        work = lifecycle.ensure_work(record, migration.target)
        lifecycle.control(self.admin, migration.pk, 'pause')
        count = len(self.fake.calls)
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=self.fake))
        self.assertEqual(len(self.fake.calls), count)
        lifecycle.control(self.admin, migration.pk, 'resume')
        self.assertTrue(lifecycle.perform_work(work.pk, embedder=self.fake))

    def test_cancel_during_remote_call_cannot_publish_candidate(self):
        record = self.source()
        migration = self.migration()
        work = lifecycle.ensure_work(record, migration.target)
        client = FakeEmbedder()
        original = client.embed_query
        def cancel(text, output_dimensionality=None):
            lifecycle.control(self.admin, migration.pk, 'cancel')
            return original(text, output_dimensionality)
        client.embed_query = cancel
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=client))
        self.assertFalse(Embedding.objects.filter(document=record, space=migration.target).exists())

    def test_changed_source_cannot_publish_old_response(self):
        record = self.source()
        migration = self.migration()
        work = lifecycle.ensure_work(record, migration.target)
        client = FakeEmbedder()
        original = client.embed_query
        def change(text, output_dimensionality=None):
            with lifecycle.source_fence():
                MemoryDocument.objects.filter(pk=record.pk).update(text='New synthetic source', content_hash='new-hash')
            return original(text, output_dimensionality)
        client.embed_query = change
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=client))
        self.assertFalse(Embedding.objects.filter(document=record, space=migration.target).exists())
        self.assertFalse(Memory(scope='site', embedder=self.fake).recall('source'))

    def test_interrupted_lease_is_recovered_without_trusting_broker(self):
        record = self.source()
        migration = self.migration()
        work = lifecycle.ensure_work(record, migration.target)
        token = work.lease_token
        EmbeddingWork.objects.filter(pk=work.pk).update(status='running', attempts=1, started_at=timezone.now()-timedelta(minutes=10))
        lifecycle.tick(dispatch=False, validate=False)
        work.refresh_from_db()
        self.assertEqual(work.status, 'retry')
        self.assertNotEqual(token, work.lease_token)
        self.assertEqual(work.error_code, 'WORKER_INTERRUPTED')

    def test_broker_failure_preserves_authoritative_work_row(self):
        record = MemoryDocument.objects.create(text='Synthetic', scope='site', content_hash='hash')
        work = lifecycle.ensure_work(record, self.active)
        with patch('knowledge_base.tasks.process_embedding_work.delay', side_effect=RuntimeError('PRIVATE credentials')):
            lifecycle.enqueue_work(work.pk)
        work.refresh_from_db()
        self.assertEqual(work.status, 'queued')
        self.assertIsNone(work.dispatched_at)

    def test_library_checkpoints_do_not_repeat_successful_prefix(self):
        document = self.library()
        client = FakeEmbedder()
        original = client.embed_query
        calls = []
        def fail_second(text, output_dimensionality=None):
            calls.append(text)
            if len(calls) == 2:
                return [1, 0]  # Permanently wrong dimensions; explicit retry below.
            return original(text, output_dimensionality)
        client.embed_query = fail_second
        parser = Mock(return_value=[('A', 'a' * 1000), ('B', 'b' * 1000), ('C', 'c' * 1000)])
        with self.assertRaises(ValueError):
            process_version(document.current_version_id, embedder=client, extractor=parser)
        prefix = calls[0]
        self.assertEqual(Embedding.objects.filter(space=self.active, document__scope='library').count(), 1)
        mutate(self.staff, document.pk, document.current_version_id, 'retry')
        process_version(document.current_version_id, embedder=client, extractor=parser)
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(calls.count(prefix), 1)
        document.current_version.refresh_from_db()
        self.assertTrue(document.current_version.extraction_complete)
        self.assertEqual(document.current_version.processing_state, 'ready')

    def test_revocation_during_candidate_call_discards_vector(self):
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        migration = self.migration()
        source = document.current_version.chunks.get().memory_document
        work = lifecycle.ensure_work(source, migration.target)
        client = FakeEmbedder()
        original = client.embed_query
        def revoke(text, output_dimensionality=None):
            mutate(self.admin, document.pk, document.current_version_id, 'clear', data={'classification': 'restricted', 'reason': 'Revoked AI permission'})
            return original(text, output_dimensionality)
        client.embed_query = revoke
        self.assertFalse(lifecycle.perform_work(work.pk, embedder=client))
        self.assertFalse(Embedding.objects.filter(document=source, space=migration.target).exists())
        self.assertFalse(lifecycle.sources(library_only=True).exists())

    def test_missing_library_coverage_blocks_cutover_even_with_force(self):
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        migration = self.migration()
        from ai_workflows.harness import reembed
        with self.assertRaises(ValidationError):
            reembed.activate(migration.target, require_complete=False, embedder=self.fake)
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)

    def test_complete_query_validated_cutover_retains_old_vectors(self):
        record = self.source()
        migration = self.migration(auto_activate=True)
        self.assertTrue(lifecycle.perform_work(lifecycle.ensure_work(record, migration.target).pk, embedder=self.fake))
        with patch('knowledge_base.indexes.ensure_index'), patch('knowledge_base.indexes.index_exists', return_value=True):
            lifecycle.validate_migration(migration, embedder=self.fake)
        migration.refresh_from_db()
        self.assertEqual(migration.status, 'active')
        self.assertIsNone(migration.active_slot)
        self.assertEqual(EmbeddingSpace.active().pk, migration.target_id)
        self.assertTrue(Embedding.objects.filter(document=record, space=self.active).exists())
        self.assertTrue(LibraryAudit.objects.filter(action='embedding_profile_activated').exists())

    def test_cutover_rechecks_sources_added_during_health_probe(self):
        record = self.source()
        migration = self.migration(auto_activate=True)
        lifecycle.perform_work(lifecycle.ensure_work(record, migration.target).pk, embedder=self.fake)
        client = FakeEmbedder()
        original = client.embed_query
        def add_source(text, output_dimensionality=None):
            with lifecycle.source_fence():
                MemoryDocument.objects.create(text='Late source', content_hash='late', scope='site')
            return original(text, output_dimensionality)
        client.embed_query = add_source
        with patch('knowledge_base.indexes.ensure_index'), patch('knowledge_base.indexes.index_exists', return_value=True):
            lifecycle.validate_migration(migration, embedder=client)
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)
        migration.refresh_from_db()
        self.assertNotEqual(migration.status, 'active')

    def test_single_unfinished_migration_and_admin_only(self):
        self.migration()
        with self.assertRaises(ValidationError):
            lifecycle.start_migration(self.admin, model='gemini-embedding-001', backend='vertex', dimensions=1536)
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            lifecycle.start_migration(self.staff, model='gemini-embedding-001', backend='vertex', dimensions=1536)

    def test_admin_page_and_controls_are_private_and_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get('/library/embeddings/').status_code, 302)
        client.force_login(self.staff)
        self.assertEqual(client.get('/library/embeddings/').status_code, 403)
        client.force_login(self.admin)
        response = client.get('/library/embeddings/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertContains(response, 'Vertex AI')
        self.assertEqual(client.post('/library/embeddings/control/', {'operation': 'retry_failed', 'space_id': self.active.pk}).status_code, 403)

    def test_admin_creation_requires_explicit_cost_consent(self):
        self.client.force_login(self.admin)
        data = {'model': 'gemini-embedding-2', 'backend': 'vertex', 'dimensions': 768, 'auto_activate': 'on'}
        self.assertEqual(self.client.post('/library/embeddings/', data).status_code, 200)
        self.assertFalse(EmbeddingMigration.objects.exists())
        response = self.client.post('/library/embeddings/', {**data, 'confirm_cost': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EmbeddingMigration.objects.get().auto_activate)
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)

    def test_initial_broker_failure_recovers_automatically(self):
        document = self.library()
        version = document.current_version
        from knowledge_base.models import LibraryVersion
        LibraryVersion.objects.filter(pk=version.pk).update(processing_state='failed', safe_error_code='QUEUE_UNAVAILABLE', created_at=timezone.now()-timedelta(minutes=10))
        with patch('knowledge_base.library.services.enqueue'), patch.object(lifecycle, 'tick'):
            maintain_embeddings()
        version.refresh_from_db()
        self.assertEqual(version.processing_state, 'queued')

    def test_credential_refresh_revocation_is_checked_before_private_payload(self):
        from unittest.mock import PropertyMock
        from ai_workflows.harness.embeddings import GoogleEmbeddingClient
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        migration = self.migration()
        work = lifecycle.ensure_work(document.current_version.chunks.get().memory_document, migration.target)
        client = GoogleEmbeddingClient(model='gemini-embedding-2', backend='vertex', dimensions=768)
        sdk = Mock()
        def delayed_credentials():
            mutate(self.admin, document.pk, document.current_version_id, 'clear', data={'classification': 'restricted', 'reason': 'Revoked while authenticating'})
            return sdk
        with patch.object(GoogleEmbeddingClient, 'client', new_callable=PropertyMock, side_effect=delayed_credentials):
            self.assertFalse(lifecycle.perform_work(work.pk, embedder=client))
        sdk.models.embed_content.assert_not_called()
        self.assertIsNone(client.before_send)
        work.refresh_from_db()
        self.assertEqual(work.status, 'cancelled')

    def test_dispatch_is_bounded_instead_of_filling_broker_with_duplicates(self):
        work = []
        for i in range(10):
            record = MemoryDocument.objects.create(scope='site', text=f'Synthetic {i}', content_hash=str(i))
            work.append(lifecycle.ensure_work(record, self.active))
        with patch('knowledge_base.tasks.process_embedding_work.delay') as dispatch:
            for item in work:
                lifecycle.enqueue_work(item.pk)
            self.assertEqual(dispatch.call_count, lifecycle.MAX_DISPATCHED)
            lifecycle.tick(validate=False)
            self.assertEqual(dispatch.call_count, lifecycle.MAX_DISPATCHED)

    def test_invalid_stored_vectors_are_not_coverage(self):
        record = self.source()
        migration = self.migration()
        Embedding.objects.create(space=migration.target, document=record, provider='gemini', model_id=migration.target.model_id,
            dimensions=768, vector=[0.0]*768)
        self.assertTrue(lifecycle.pending(migration.target).filter(pk=record.pk).exists())
        lifecycle.perform_work(lifecycle.ensure_work(record, migration.target).pk, embedder=self.fake)
        self.assertFalse(lifecycle.pending(migration.target).exists())

    def test_query_clients_follow_stored_profile_not_global_model_config(self):
        memory = Memory()
        first = memory._client_for(self.active)
        migration = self.migration()
        second = memory._client_for(migration.target)
        self.assertIsNot(first, second)
        self.assertEqual(second.model, 'gemini-embedding-2')
        self.assertEqual(second.dimensions, 768)
        self.assertEqual(second.backend, 'vertex')
        self.assertEqual(second.protocol, 'retrieval_v1')

    def test_validated_rollback_reuses_retained_vectors(self):
        record = self.source()
        retired = EmbeddingSpace.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=768,
            api_backend='vertex', input_protocol='retrieval_v1', status='retired')
        Embedding.objects.create(space=retired, document=record, provider='gemini', model_id=retired.model_id,
            dimensions=768, vector=[1.0]+[0.0]*767)
        migration = lifecycle.start_migration(self.admin, model=retired.model_id, backend='vertex', dimensions=768, target=retired, auto_activate=True)
        self.assertTrue(lifecycle.preflight(migration, embedder=self.fake))
        self.assertFalse(lifecycle.pending(retired).exists())
        with patch('knowledge_base.indexes.ensure_index'), patch('knowledge_base.indexes.index_exists', return_value=True):
            lifecycle.validate_migration(migration, embedder=self.fake)
        self.assertEqual(EmbeddingSpace.active().pk, retired.pk)
        self.assertTrue(Embedding.objects.filter(space=self.active, document=record).exists())

    def test_no_active_profile_still_retains_source_for_later_build(self):
        EmbeddingSpace.objects.filter(status='active').update(status='retired')
        with self.assertRaises(MemoryUnavailable):
            self.source()
        record = MemoryDocument.objects.get(scope='site')
        self.assertEqual(self.fake.calls, [])
        migration = self.migration()
        self.assertTrue(lifecycle.perform_work(lifecycle.ensure_work(record, migration.target).pk, embedder=self.fake))

    def test_generic_writes_cannot_bypass_library_clearance_by_model_or_scope(self):
        document = self.library()
        for scope, obj in [('library', None), ('site', document)]:
            with self.subTest(scope=scope), self.assertRaises(MemoryUnavailable):
                Memory(scope=scope, embedder=self.fake).remember('Unapproved synthetic input', obj=obj)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(MemoryDocument.objects.exists())

    def test_mistagged_library_cache_cannot_escape_into_generic_memory(self):
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        source = document.current_version.chunks.get().memory_document
        MemoryDocument.objects.filter(pk=source.pk).update(scope='site')
        self.assertFalse(lifecycle.sources().filter(pk=source.pk).exists())
        self.assertEqual(Memory(scope='site', embedder=self.fake).recall('reference', scope=None), [])

    def test_missing_library_cache_is_visible_and_repaired_without_reextracting(self):
        from ai_workflows.harness.embeddings import EmbeddingFailure
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        document.current_version.chunks.get().memory_document.delete()
        with self.assertRaises(EmbeddingFailure):
            lifecycle.coverage_guard(self.active)
        document.current_version.refresh_from_db()
        self.assertEqual(document.current_version.safe_error_code, 'LIBRARY_SOURCE_INVALID')
        mutate(self.staff, document.pk, document.current_version_id, 'retry')
        parser = Mock(side_effect=AssertionError('Successful extraction must not be repeated'))
        process_version(document.current_version_id, embedder=self.fake, extractor=parser)
        parser.assert_not_called()
        document.current_version.refresh_from_db()
        self.assertEqual(document.current_version.processing_state, 'ready')
        self.assertFalse(lifecycle.pending(self.active, library_only=True).exists())

    def test_account_deactivation_during_query_cannot_return_private_text(self):
        from knowledge_base.library.retrieval import LibraryRetrievalEngine
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        client = FakeEmbedder()
        original = client.embed_query
        def deactivate(text, output_dimensionality=None):
            get_user_model().objects.filter(pk=self.staff.pk).update(is_active=False)
            return original(text, output_dimensionality)
        client.embed_query = deactivate
        self.assertEqual(LibraryRetrievalEngine().retrieve_semantic('reference', self.staff, embedder=client), [])

    def test_admin_role_removal_during_query_cannot_keep_broad_access(self):
        from knowledge_base.library.retrieval import LibraryRetrievalEngine
        document = self.library()
        process_version(document.current_version_id, embedder=self.fake)
        client = FakeEmbedder()
        original = client.embed_query
        def remove_role(text, output_dimensionality=None):
            get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
            return original(text, output_dimensionality)
        client.embed_query = remove_role
        self.assertEqual(LibraryRetrievalEngine().retrieve_semantic('reference', self.admin, embedder=client), [])

    def test_stale_retained_vectors_cannot_be_rolled_back(self):
        record = self.source()
        retired = EmbeddingSpace.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=768,
            api_backend='vertex', input_protocol='retrieval_v1', status='retired')
        Embedding.objects.create(space=retired, document=record, provider='gemini', model_id=retired.model_id,
            dimensions=768, vector=[1.0]+[0.0]*767, content_hash='old-content-hash')
        migration = lifecycle.start_migration(self.admin, model=retired.model_id, backend='vertex', dimensions=768, target=retired, auto_activate=True)
        lifecycle.validate_migration(migration, embedder=self.fake)
        self.assertEqual(EmbeddingSpace.active().pk, self.active.pk)
        self.assertTrue(lifecycle.pending(retired).exists())
