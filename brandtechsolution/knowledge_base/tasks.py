"""Dedicated bounded document processing and privacy maintenance jobs."""
from datetime import timedelta
import hashlib
import math
import logging

from celery import shared_task
from billiard.exceptions import SoftTimeLimitExceeded
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from knowledge_base.models import (
    LibraryDocument, LibraryVersion, LibraryChunk, MemoryDocument, Embedding, EmbeddingSpace,
)
from knowledge_base.library.parsers import extract_sections, chunk_sections
from knowledge_base.library.services import audit

logger = logging.getLogger(__name__)


def _eligible(version):
    return (
        not version.document.is_deleted
        and version.document.current_version_id == version.pk
        and version.upload_authority and version.clearance_state == 'approved'
        and version.classification == 'internal_standard'
        and version.permitted_provider == 'gemini'
    )


def _clear_chunks(version):
    ids = list(version.chunks.exclude(memory_document=None).values_list('memory_document_id', flat=True))
    version.chunks.all().delete()
    MemoryDocument.objects.filter(pk__in=ids).delete()


def process_version(version_id, *, embedder=None, extractor=None):
    """Stage output off-DB; publish atomically only if the locked version is current."""
    with transaction.atomic():
        version = LibraryVersion.objects.select_related('document').get(pk=version_id)
        LibraryDocument.objects.select_for_update().get(pk=version.document_id)
        version.refresh_from_db()
        version.document.refresh_from_db()
        if not _eligible(version) or version.processing_state != 'queued':
            return
        version.processing_state = 'processing'
        version.processing_started_at = timezone.now()
        version.attempts += 1
        attempt = version.attempts
        token = version.processing_token
        version.save()
    try:
        # Check immutable original integrity before invoking any parser/provider.
        with version.original.open('rb') as original:
            digest = hashlib.file_digest(original, 'sha256').hexdigest()
        if digest != version.checksum_sha256:
            raise ValueError('CHECKSUM_MISMATCH')
        sections = (extractor or extract_sections)(version)
        chunks = chunk_sections(sections)
        space = EmbeddingSpace.active()
        if not space or space.provider != version.permitted_provider:
            raise ValueError('EMBEDDING_SPACE_NOT_CLEARED')
        if embedder is None:
            from ai_workflows.harness.llm import get_embedder
            from brandtechsolution.config import config
            if space.model_id.removeprefix('models/') != config.gemini_embedding_model.removeprefix('models/'):
                raise ValueError('EMBEDDING_MODEL_MISMATCH')
            embedder = get_embedder(provider=space.provider)
        from ai_workflows.harness.memory import Memory
        memory = Memory(embedder=embedder, scope='library')
        staged = []
        for section, text, digest in chunks:
            version.refresh_from_db()
            version.document.refresh_from_db()
            if not _eligible(version) or version.processing_state != 'processing' or version.attempts != attempt or version.processing_token != token:
                return
            from langsmith import tracing_context
            with tracing_context(enabled=False):
                vector = memory._embed(text, space)
            if len(vector) != space.dimensions or not all(math.isfinite(float(v)) for v in vector):
                raise ValueError('INVALID_EMBEDDING')
            staged.append((section, text, digest, vector))
        with transaction.atomic():
            document = LibraryDocument.objects.select_for_update().get(pk=version.document_id)
            version.refresh_from_db()
            version.document = document
            if not _eligible(version) or version.processing_state != 'processing' or version.attempts != attempt or version.processing_token != token:
                return
            if not EmbeddingSpace.objects.filter(pk=space.pk, status='active').exists():
                raise ValueError('EMBEDDING_SPACE_CHANGED')
            _clear_chunks(version)
            content_type = ContentType.objects.get_for_model(LibraryChunk)
            for ordinal, (section, text, digest, vector) in enumerate(staged):
                chunk = LibraryChunk.objects.create(version=version, ordinal=ordinal, text=text, page_or_section=section, content_hash=digest)
                record = MemoryDocument.objects.create(
                    content_type=content_type, object_id=chunk.pk, scope='library', kind='library_chunk',
                    title=document.title, text=text, content_hash=digest,
                )
                Embedding.objects.create(document=record, space=space, provider=space.provider, model_id=space.model_id, dimensions=space.dimensions, vector=vector)
                chunk.memory_document = record
                chunk.save(update_fields=['memory_document'])
            version.processing_state = 'ready'
            version.safe_error_code = ''
            version.save()
            audit(document, None, 'processing_ready', version, chunks=len(staged), space_id=space.pk)
    except Exception as exc:
        safe_codes = {
            'CHECKSUM_MISMATCH', 'EMBEDDING_SPACE_NOT_CLEARED', 'EMBEDDING_MODEL_MISMATCH',
            'INVALID_EMBEDDING', 'EMBEDDING_SPACE_CHANGED', 'PAGE_LIMIT_EXCEEDED',
            'TEXT_LIMIT_EXCEEDED', 'CHUNK_LIMIT_EXCEEDED', 'NO_EXTRACTABLE_TEXT', 'ENCRYPTED_PDF',
        }
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_codes else 'PROCESSING_FAILED'
        if isinstance(exc, (SoftTimeLimitExceeded, TimeoutError)):
            code = 'TIMEOUT_EXCEEDED'
        LibraryVersion.objects.filter(pk=version_id, processing_state='processing', attempts=attempt, processing_token=token).update(
            processing_state='failed', safe_error_code=code,
        )
        # Do not log exception messages: providers/parsers may echo private text.
        logger.warning('Library processing failed: version=%s code=%s type=%s', version_id, code, type(exc).__name__)
        raise


@shared_task(bind=True, queue='library_processing', soft_time_limit=55, time_limit=60, max_retries=2)
def process_library_version(self, version_id):
    try:
        process_version(version_id)
    except LibraryVersion.DoesNotExist:
        return
    except Exception as exc:
        version = LibraryVersion.objects.select_related('document').filter(pk=version_id).first()
        if version and _eligible(version) and version.attempts < 3 and version.safe_error_code == 'PROCESSING_FAILED':
            LibraryVersion.objects.filter(pk=version_id, processing_state='failed').update(processing_state='queued')
            raise self.retry(countdown=30 * (2 ** self.request.retries), exc=RuntimeError('Library processing failed')) from None
        # State already records failure; no document/provider text in Celery results.
        return


@shared_task
def maintain_library():
    """Purge promptly (rather than waiting 30 days); recover jobs killed by hard limits."""
    stale = timezone.now() - timedelta(minutes=5)
    LibraryVersion.objects.filter(processing_state='processing', processing_started_at__lt=stale).update(
        processing_state='failed', safe_error_code='WORKER_INTERRUPTED',
    )
    from knowledge_base.library.services import enqueue
    for pk in LibraryVersion.objects.filter(processing_state='queued', created_at__lt=stale).values_list('pk', flat=True)[:100]:
        enqueue(pk)
    for pk in LibraryDocument.objects.filter(is_deleted=True).values_list('pk', flat=True).iterator():
        with transaction.atomic():
            doc = LibraryDocument.objects.select_for_update().get(pk=pk)
            for version in doc.versions.all():
                version.original.delete(save=False)
                _clear_chunks(version)
            # Audit survives without titles, filenames or extracted content.
            audit(doc, None, 'purged')
            doc.delete()
    # Filesystem writes are not transactional. Clean up originals left by a
    # rolled-back upload without racing a currently uncommitted upload.
    from pathlib import Path
    from knowledge_base.library.storage import library_storage
    originals = Path(library_storage.location) / 'originals'
    cutoff = (timezone.now() - timedelta(days=1)).timestamp()
    cleaned = 0
    for path in originals.glob('*'):
        if path.is_file() and path.stat().st_mtime < cutoff:
            key = f'originals/{path.name}'
            if not LibraryVersion.objects.filter(original=key).exists():
                library_storage.delete(key)
                cleaned += 1
                if cleaned >= 500:
                    break
