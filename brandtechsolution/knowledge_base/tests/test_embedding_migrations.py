"""Apply/rollback/reapply against the isolated test DB, never application data."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class EmbeddingSchemaMigrationTests(TransactionTestCase):
    def test_legacy_provenance_backfill_and_round_trip_preserve_vectors(self):
        old = [('knowledge_base', '0006_librarydocument_tags')]
        new = [('knowledge_base', '0008_embeddingspace_consecutive_failures_and_more')]
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            User = apps.get_model('auth', 'User')
            Space = apps.get_model('knowledge_base', 'EmbeddingSpace')
            Document = apps.get_model('knowledge_base', 'MemoryDocument')
            Vector = apps.get_model('knowledge_base', 'Embedding')
            Library = apps.get_model('knowledge_base', 'LibraryDocument')
            Version = apps.get_model('knowledge_base', 'LibraryVersion')
            owner = User.objects.create(username='migration-fixture')
            space = Space.objects.create(provider='gemini', model_id='gemini-embedding-001', dimensions=3)
            source = Document.objects.create(text='Sanitized legacy source', content_hash='legacy-hash')
            vector = Vector.objects.create(space=space, document=source, provider='gemini', model_id=space.model_id, dimensions=3, vector=[1, 0, 0])
            library = Library.objects.create(owner_id=owner.pk, title='Migration fixture')
            version = Version.objects.create(document=library, version_number=1, original='originals/never-opened',
                original_filename='fixture.txt', detected_format='txt', size_bytes=1, checksum_sha256='0'*64,
                uploader_id=owner.pk, processing_state='ready')
            pending = Version.objects.create(document=library, version_number=2, original='originals/never-opened-2',
                original_filename='fixture.txt', detected_format='txt', size_bytes=1, checksum_sha256='0'*64,
                uploader_id=owner.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(new)
            apps = executor.loader.project_state(new).apps
            Vector = apps.get_model('knowledge_base', 'Embedding')
            Space = apps.get_model('knowledge_base', 'EmbeddingSpace')
            Version = apps.get_model('knowledge_base', 'LibraryVersion')
            self.assertEqual(Vector.objects.get(pk=vector.pk).content_hash, 'legacy-hash')
            self.assertEqual(list(Vector.objects.get(pk=vector.pk).vector), [1, 0, 0])
            self.assertEqual(Space.objects.get(pk=space.pk).api_backend, 'configured')
            self.assertEqual(Space.objects.get(pk=space.pk).input_protocol, 'legacy')
            self.assertTrue(Version.objects.get(pk=version.pk).extraction_complete)
            self.assertFalse(Version.objects.get(pk=pending.pk).extraction_complete)
            MigrationExecutor(connection).migrate(old)
            executor = MigrationExecutor(connection)
            executor.migrate(new)
            apps = executor.loader.project_state(new).apps
            restored = apps.get_model('knowledge_base', 'Embedding').objects.get(pk=vector.pk)
            self.assertEqual(restored.content_hash, 'legacy-hash')
            self.assertEqual(list(restored.vector), [1, 0, 0])
        finally:
            MigrationExecutor(connection).migrate(new)
