"""Dedicated bounded document processing and privacy maintenance jobs."""
from datetime import timedelta
import hashlib
import logging

from celery import shared_task
from billiard.exceptions import SoftTimeLimitExceeded
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from knowledge_base.models import LibraryDocument, LibraryVersion, LibraryChunk, MemoryDocument, EmbeddingSpace
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
    """Checkpoint local extraction once; each vector has a separate durable job."""
    from .embedding_lifecycle import source_fence, ensure_work, perform_work, enqueue_work
    with source_fence():
        version = LibraryVersion.objects.select_related('document').get(pk=version_id)
        LibraryDocument.objects.select_for_update().get(pk=version.document_id)
        version.refresh_from_db()
        version.document.refresh_from_db()
        if not _eligible(version) or version.processing_state != 'queued':
            return
        version.processing_state = 'processing'
        version.processing_started_at = timezone.now()
        if version.extraction_complete and not version.chunks.exists():
            version.extraction_complete = False
        if not version.extraction_complete:
            version.attempts += 1
        attempt, token = version.attempts, version.processing_token
        version.save()
    try:
        if not version.extraction_complete:
            # Check immutable original integrity before invoking any parser/provider.
            with version.original.open('rb') as original:
                digest = hashlib.file_digest(original, 'sha256').hexdigest()
            if digest != version.checksum_sha256:
                raise ValueError('CHECKSUM_MISMATCH')
            sections = (extractor or extract_sections)(version)
            chunks = chunk_sections(sections)
            with source_fence():
                document = LibraryDocument.objects.select_for_update().get(pk=version.document_id)
                version.refresh_from_db()
                version.document = document
                if not _eligible(version) or version.processing_state != 'processing' or version.processing_token != token:
                    return
                _clear_chunks(version)
                content_type = ContentType.objects.get_for_model(LibraryChunk)
                for ordinal, (section, text, digest) in enumerate(chunks):
                    chunk = LibraryChunk.objects.create(version=version, ordinal=ordinal, text=text, page_or_section=section, content_hash=digest)
                    record = MemoryDocument.objects.create(content_type=content_type, object_id=chunk.pk, scope='library',
                        kind='library_chunk', title=document.title, text=text, content_hash=digest)
                    chunk.memory_document = record
                    chunk.save(update_fields=['memory_document'])
                version.extraction_complete = True
                version.save(update_fields=['extraction_complete'])
        space = EmbeddingSpace.active()
        if not space or space.provider != version.permitted_provider:
            raise ValueError('EMBEDDING_SPACE_NOT_CLEARED')
        work = []
        with source_fence():
            version.refresh_from_db()
            version.document.refresh_from_db()
            if not _eligible(version) or version.processing_token != token:
                return
            for chunk in version.chunks.select_related('memory_document'):
                record = chunk.memory_document
                if record is None:
                    record, _ = MemoryDocument.objects.get_or_create(content_type=ContentType.objects.get_for_model(LibraryChunk),
                        object_id=chunk.pk, defaults={'scope': 'library', 'kind': 'library_chunk', 'title': version.document.title,
                            'text': chunk.text, 'content_hash': chunk.content_hash})
                    chunk.memory_document = record
                    chunk.save(update_fields=['memory_document'])
                if record.text != chunk.text or record.content_hash != chunk.content_hash or record.scope not in {'library', 'staff_library'}:
                    record.text, record.content_hash, record.scope, record.kind = chunk.text, chunk.content_hash, 'library', 'library_chunk'
                    record.save(update_fields=['text', 'content_hash', 'scope', 'kind', 'updated_at'])
                work.append(ensure_work(record, space))
        if embedder is not None:
            # Explicit test/CLI injection can finish synchronously. Real workers
            # never hold hundreds of provider responses in RAM or re-pay a prefix.
            for item in work:
                if not perform_work(item.pk, embedder=embedder):
                    item.refresh_from_db()
                    if item.status in {'blocked', 'exhausted'}:
                        raise ValueError(item.error_code)
        else:
            for item in work[:4]:
                transaction.on_commit(lambda pk=item.pk: enqueue_work(pk))
        from .embedding_lifecycle import _finish_initial
        with source_fence():
            _finish_initial(version.pk)
        audit(version.document, None, 'extraction_checkpointed', version, chunks=len(work), space_id=space.pk)
    except Exception as exc:
        safe_codes = {'CHECKSUM_MISMATCH', 'EMBEDDING_SPACE_NOT_CLEARED', 'INVALID_EMBEDDING',
            'PAGE_LIMIT_EXCEEDED', 'TEXT_LIMIT_EXCEEDED', 'CHUNK_LIMIT_EXCEEDED',
            'NO_EXTRACTABLE_TEXT', 'ENCRYPTED_PDF'}
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in safe_codes else 'PROCESSING_FAILED'
        if isinstance(exc, (SoftTimeLimitExceeded, TimeoutError)):
            code = 'TIMEOUT_EXCEEDED'
        LibraryVersion.objects.filter(pk=version_id, processing_state='processing', attempts=attempt, processing_token=token).update(
            processing_state='failed', safe_error_code=code)
        # Do not log exception messages: providers/parsers may echo private text.
        logger.warning('Library processing failed: version=%s code=%s type=%s', version_id, code, type(exc).__name__)
        raise


@shared_task(bind=True, queue='library_processing', soft_time_limit=55, time_limit=60, max_retries=2)
def process_library_version(self, version_id):
    try:
        process_version(version_id)
    except LibraryVersion.DoesNotExist:
        return
    except Exception:
        version = LibraryVersion.objects.select_related('document').filter(pk=version_id).first()
        if version and _eligible(version) and version.attempts < 3 and version.safe_error_code in {'PROCESSING_FAILED', 'TIMEOUT_EXCEEDED'}:
            LibraryVersion.objects.filter(pk=version_id, processing_state='failed').update(processing_state='queued')
            raise self.retry(countdown=30 * (2 ** self.request.retries), exc=RuntimeError('Library processing failed')) from None
        # State already records failure; no document/provider text in Celery results.
        return


@shared_task(queue='library_processing', soft_time_limit=50, time_limit=60)
def process_embedding_work(work_id):
    from .embedding_lifecycle import perform_work
    return perform_work(work_id)


@shared_task(soft_time_limit=100, time_limit=110)
def maintain_embeddings():
    from .embedding_lifecycle import tick, source_fence
    from .library.services import enqueue
    import uuid
    LibraryVersion.objects.filter(processing_state='processing', extraction_complete=False,
        processing_started_at__lt=timezone.now()-timedelta(minutes=5)).update(processing_state='failed', safe_error_code='WORKER_INTERRUPTED')
    tick()
    # Recover initial extraction/broker interruptions separately from per-vector
    # retries. Successful extraction is never thrown away to retry embeddings.
    candidates = LibraryVersion.objects.filter(extraction_complete=False, processing_state='failed', attempts__lt=3,
        safe_error_code__in=['QUEUE_UNAVAILABLE', 'WORKER_INTERRUPTED', 'PROCESSING_FAILED', 'TIMEOUT_EXCEEDED'])[:100]
    for candidate in candidates:
        last = candidate.processing_started_at or candidate.created_at
        if last + timedelta(seconds=min(1800, 30 * 2 ** candidate.attempts)) > timezone.now():
            continue
        with source_fence():
            version = LibraryVersion.objects.select_for_update().select_related('document').get(pk=candidate.pk)
            if not _eligible(version) or version.processing_state != 'failed':
                continue
            version.processing_state = 'queued'
            version.processing_token = uuid.uuid4()
            version.save(update_fields=['processing_state', 'processing_token'])
            transaction.on_commit(lambda pk=version.pk: enqueue(pk))


@shared_task
def maintain_library():
    """Purge promptly (rather than waiting 30 days); recover jobs killed by hard limits."""
    stale = timezone.now() - timedelta(minutes=5)
    LibraryVersion.objects.filter(processing_state='processing', extraction_complete=False, processing_started_at__lt=stale).update(
        processing_state='failed', safe_error_code='WORKER_INTERRUPTED')
    from knowledge_base.library.services import enqueue
    from knowledge_base.library.previews import purge_preview, clean_orphan_previews
    for pk in LibraryVersion.objects.filter(processing_state='queued', created_at__lt=stale).values_list('pk', flat=True)[:100]:
        enqueue(pk)
    for pk in LibraryDocument.objects.filter(is_deleted=True).values_list('pk', flat=True).iterator():
        with transaction.atomic():
            doc = LibraryDocument.objects.select_for_update().get(pk=pk)
            for version in doc.versions.all():
                version.original.delete(save=False)
                purge_preview(version)
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
    clean_orphan_previews(cutoff)
    cleaned = 0
    for path in originals.glob('*'):
        if path.is_file() and path.stat().st_mtime < cutoff:
            key = f'originals/{path.name}'
            if not LibraryVersion.objects.filter(original=key).exists():
                library_storage.delete(key)
                cleaned += 1
                if cleaned >= 500:
                    break
