"""Durable embedding work and complete-coverage cutover. No private text in errors."""
from contextlib import contextmanager
from datetime import timedelta
import logging
import random
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Exists, F, OuterRef, Q, Func, IntegerField, FloatField
from django.utils import timezone

from ai_workflows.harness.embeddings import GoogleEmbeddingClient, EmbeddingFailure, classify_failure, validate_vector, GOOGLE_MODEL_CHOICES, SUPPORTED_DIMENSIONS
from .models import Embedding, EmbeddingMigration, EmbeddingSpace, EmbeddingWork, LibraryChunk, LibraryVersion, MemoryDocument
from .library.policy import LibraryPolicy
from .library.retrieval import PROTECTED_LIBRARY_SCOPES
from .library.services import audit

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 6
LEASE_SECONDS = 180
MAX_DISPATCHED = 4  # Two calls plus a small buffer for the two-process private worker.
PROTECTED = PROTECTED_LIBRARY_SCOPES


@contextmanager
def source_fence():
    """Serialize canonical source writes and the final coverage/cutover check."""
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [74144219])
        yield


def library_versions():
    return LibraryVersion.objects.filter(pk=F('document__current_version_id'), document__is_deleted=False,
        clearance_state='approved', upload_authority=True, classification='internal_standard',
        permitted_provider='gemini', extraction_complete=True)


def library_chunks():
    return LibraryChunk.objects.filter(version_id__in=library_versions().values('pk'))


def verified_library_chunks():
    return library_chunks().filter(memory_document__scope__in=PROTECTED,
        memory_document__text=F('text'), memory_document__content_hash=F('content_hash'))


def generic_sources():
    # Both the scope and model/back-reference matter. A stale/mistagged cache
    # must never turn a private Library object into an unrestricted source.
    return MemoryDocument.objects.exclude(scope__in=PROTECTED).filter(library_chunk__isnull=True).exclude(
        content_type__app_label='knowledge_base', content_type__model__in=['librarydocument', 'libraryversion', 'librarychunk'])


def sources(*, library_only=False):
    library_ids = verified_library_chunks().values('memory_document_id')
    rows = MemoryDocument.objects.filter(pk__in=library_ids)
    if not library_only:
        rows = MemoryDocument.objects.filter(Q(pk__in=generic_sources().values('pk')) | Q(pk__in=library_ids))
    return rows


def current_vectors(space):
    rows = Embedding.objects.filter(space=space, provider=space.provider, model_id=space.model_id,
        dimensions=space.dimensions, content_hash=F('document__content_hash'))
    if connection.vendor == 'postgresql':
        rows = rows.annotate(_width=Func(F('vector'), function='vector_dims', output_field=IntegerField()),
            _norm=Func(F('vector'), function='vector_norm', output_field=FloatField())).filter(_width=space.dimensions, _norm__gt=0)
    return rows


def pending(space, *, library_only=False):
    current = current_vectors(space).filter(document_id=OuterRef('pk'))
    return sources(library_only=library_only).annotate(vector_current=Exists(current)).filter(vector_current=False)


def ensure_work(document, space, *, reset=False):
    work, _ = EmbeddingWork.objects.get_or_create(document=document, space=space, defaults={'source_hash': document.content_hash})
    missing_done = work.status == 'done' and not current_vectors(space).filter(document=document).exists()
    if work.source_hash != document.content_hash or reset or work.status == 'cancelled' or missing_done:
        EmbeddingWork.objects.filter(pk=work.pk).update(source_hash=document.content_hash, status='queued', attempts=0,
            error_code='', next_attempt_at=timezone.now(), lease_token=uuid.uuid4(), dispatched_at=None, updated_at=timezone.now())
        work.refresh_from_db()
    return work


def enqueue_work(pk):
    from .tasks import process_embedding_work
    now = timezone.now()
    with source_fence():
        in_flight = EmbeddingWork.objects.filter(Q(status='running') | Q(status__in=['queued', 'retry'], dispatched_at__gte=now-timedelta(seconds=LEASE_SECONDS))).count()
        if in_flight >= MAX_DISPATCHED:
            return
        changed = EmbeddingWork.objects.filter(pk=pk, status__in=['queued', 'retry'], next_attempt_at__lte=now).filter(
            Q(dispatched_at=None) | Q(dispatched_at__lt=now-timedelta(seconds=LEASE_SECONDS))).update(dispatched_at=now)
    if not changed:
        return
    try:
        process_embedding_work.delay(pk)
    except Exception:
        # The durable queued row remains authoritative; maintenance will retry dispatch.
        EmbeddingWork.objects.filter(pk=pk, dispatched_at=now).update(dispatched_at=None)
        logger.warning('Embedding work broker unavailable: work=%s', pk)


def _allowed_space(space, *, finishing=False):
    if not finishing and EmbeddingSpace.objects.filter(pk=space.pk).filter(Q(needs_attention=True) | Q(retry_after__gt=timezone.now())).exists():
        return False
    states = ['building', 'ready', 'paused', 'blocked'] if finishing else ['building', 'ready']
    return EmbeddingSpace.objects.filter(pk=space.pk, status=EmbeddingSpace.ACTIVE).exists() or EmbeddingMigration.objects.filter(
        active_slot=1, target=space, status__in=states, preflight_passed=True).exists()


def _finish_initial(version_id):
    version = LibraryVersion.objects.select_related('document').filter(pk=version_id).first()
    active = EmbeddingSpace.active()
    if not version or not active or not library_chunks().filter(version=version).exists():
        return
    if library_chunks().filter(version=version).exclude(pk__in=verified_library_chunks().values('pk')).exists():
        LibraryVersion.objects.filter(pk=version.pk).update(processing_state='failed', safe_error_code='LIBRARY_SOURCE_INVALID')
        return
    missing = pending(active, library_only=True).filter(library_chunk__version=version).exists()
    if not missing and version.processing_state != 'ready':
        version.processing_state = 'ready'
        version.safe_error_code = ''
        version.save(update_fields=['processing_state', 'safe_error_code'])
        audit(version.document, None, 'processing_ready', version, space_id=active.pk)


def perform_work(pk, *, embedder=None):
    """One paid call per lease, checkpoint immediately, reject stale/uncleared results."""
    with source_fence():
        work = EmbeddingWork.objects.select_for_update().select_related('space', 'document').filter(pk=pk).first()
        if not work or work.status not in {'queued', 'retry'} or work.next_attempt_at > timezone.now():
            return False
        if not _allowed_space(work.space):
            return False
        document, space = work.document, work.space
        if not sources().filter(pk=document.pk).exists():
            work.status = 'cancelled'
            work.save(update_fields=['status', 'updated_at'])
            return False
        if current_vectors(space).filter(document=document).exists():
            work.status = 'done'
            work.error_code = ''
            work.save(update_fields=['status', 'error_code', 'updated_at'])
            return True
        if work.attempts >= MAX_ATTEMPTS:
            work.status = 'exhausted'
            work.save(update_fields=['status', 'updated_at'])
            chunk = LibraryChunk.objects.filter(memory_document=document).first()
            if chunk:
                LibraryVersion.objects.filter(pk=chunk.version_id, processing_token=work.clearance_token).exclude(processing_state='ready').update(processing_state='failed', safe_error_code=work.error_code or 'RETRY_BUDGET_EXHAUSTED')
            return False
        work.status = 'running'
        work.source_hash = document.content_hash
        work.attempts += 1
        work.lease_token = uuid.uuid4()
        work.started_at = timezone.now()
        chunk = LibraryChunk.objects.select_related('version').filter(memory_document=document).first()
        work.clearance_token = chunk.version.processing_token if chunk else None
        work.dispatched_at = None
        work.save()
        token, digest, text = work.lease_token, work.source_hash, document.text
    client = embedder
    previous_guard = None
    def before_send():
        # Authentication can be slow. Check again immediately before the first
        # request carrying source text, not just before credential refresh.
        with source_fence():
            leased = EmbeddingWork.objects.filter(pk=pk, status='running', lease_token=token).exists()
            current = sources().filter(pk=document.pk, content_hash=digest).exists()
            current_chunk = LibraryChunk.objects.select_related('version').filter(memory_document_id=document.pk).first()
            cleared = not current_chunk or current_chunk.version.processing_token == work.clearance_token
            if not leased or not current or not cleared or not _allowed_space(space):
                raise EmbeddingFailure('WORK_INVALIDATED')
    try:
        if client is None:
            from ai_workflows.harness.llm import get_embedder
            client = get_embedder(space=space, provider=space.provider)
        if isinstance(client, GoogleEmbeddingClient):
            previous_guard = client.before_send
            client.before_send = before_send
        from ai_workflows.harness.memory import Memory
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            vector = Memory(embedder=client)._embed(text, space, document=True)
        vector = validate_vector(vector, space.dimensions)
    except Exception as exc:
        failure = classify_failure(exc)
        with source_fence():
            current = EmbeddingWork.objects.select_for_update().filter(pk=pk, status='running', lease_token=token).first()
            if current and failure.code == 'WORK_INVALIDATED':
                current.status = 'cancelled'
                current.error_code = failure.code
                current.save(update_fields=['status', 'error_code', 'updated_at'])
                return False
            if current:
                current.status = ('retry' if current.attempts < MAX_ATTEMPTS else 'exhausted') if failure.retryable else 'blocked'
                current.error_code = failure.code
                delay = max(failure.retry_after, min(3600, 30 * 2 ** (current.attempts - 1)) + random.randint(0, 15))
                current.next_attempt_at = timezone.now() + timedelta(seconds=delay)
                current.dispatched_at = None
                current.save()
                profile = EmbeddingSpace.objects.get(pk=space.pk)
                if failure.retryable:
                    profile.consecutive_failures += 1
                    cooldown = max(delay, 3600 if profile.consecutive_failures >= MAX_ATTEMPTS else 0)
                    profile.retry_after = timezone.now() + timedelta(seconds=cooldown)
                elif failure.code in {'AUTHENTICATION_OR_PERMISSION', 'MODEL_OR_REQUEST_INVALID', 'VERTEX_CREDENTIAL_CONFIGURATION', 'DEVELOPER_API_CREDENTIAL_CONFIGURATION', 'INVALID_PROFILE', 'MODEL_PROTOCOL_UNSUPPORTED'}:
                    profile.needs_attention = True
                profile.last_error_code = failure.code
                profile.save(update_fields=['consecutive_failures', 'retry_after', 'needs_attention', 'last_error_code'])
                chunk = LibraryChunk.objects.filter(memory_document_id=document.pk).first()
                if chunk and current.status in {'blocked', 'exhausted'}:
                    LibraryVersion.objects.filter(pk=chunk.version_id, processing_token=current.clearance_token).exclude(processing_state='ready').update(
                        processing_state='failed', safe_error_code=failure.code)
        logger.warning('Embedding work failed: work=%s code=%s', pk, failure.code)
        return False
    finally:
        if isinstance(client, GoogleEmbeddingClient):
            client.before_send = previous_guard
        if embedder is None and client is not None and hasattr(client, 'close'):
            client.close()
    with source_fence():
        current = EmbeddingWork.objects.select_for_update().filter(pk=pk, status='running', lease_token=token).first()
        source = MemoryDocument.objects.filter(pk=document.pk).first()
        if not current or not source:
            return False
        chunk = LibraryChunk.objects.select_related('version').filter(memory_document=source).first()
        stale_clearance = chunk and chunk.version.processing_token != current.clearance_token
        if not sources().filter(pk=source.pk).exists() or not _allowed_space(space, finishing=True) or stale_clearance:
            current.status = 'cancelled'
        elif source.content_hash != digest:
            current.status = 'queued'
            current.source_hash = source.content_hash
            current.attempts = 0
            current.next_attempt_at = timezone.now()
        else:
            Embedding.objects.update_or_create(space=space, document=source, defaults={
                'provider': space.provider, 'model_id': space.model_id, 'dimensions': space.dimensions,
                'vector': vector, 'content_hash': digest,
            })
            current.status, current.error_code = 'done', ''
            EmbeddingSpace.objects.filter(pk=space.pk).update(consecutive_failures=0, retry_after=None, last_error_code='')
        current.save()
        chunk = LibraryChunk.objects.filter(memory_document_id=source.pk).first()
        if chunk:
            _finish_initial(chunk.version_id)
        return current.status == 'done'


def require_admin(actor):
    if not actor or not actor.is_active or not actor.is_staff or not LibraryPolicy.is_administrator(actor):
        raise PermissionDenied


def start_migration(actor, *, model, backend='vertex', dimensions=1536, auto_activate=False, target=None):
    require_admin(actor)
    if (target is None and (model not in dict(GOOGLE_MODEL_CHOICES) or dimensions not in SUPPORTED_DIMENSIONS)) or backend not in {'vertex', 'developer_api'}:
        raise ValidationError('Choose a supported Google embedding profile.')
    with source_fence():
        if EmbeddingMigration.objects.filter(active_slot=1).exists():
            raise ValidationError('Pause/resume or cancel the current migration before starting another.')
        if target is not None:
            target = EmbeddingSpace.objects.select_for_update().get(pk=target.pk)
        previous = EmbeddingSpace.active()
        if target is None:
            target = EmbeddingSpace.objects.create(provider='gemini', model_id=model, dimensions=dimensions,
                                                    api_backend=backend, input_protocol='retrieval_v1')
        elif target.status == EmbeddingSpace.ACTIVE:
            raise ValidationError('This profile is already active.')
        elif target.provider != 'gemini' or target.model_id.removeprefix('models/') != model or target.dimensions != dimensions or target.resolved_backend != backend:
            raise ValidationError('Rollback parameters must match the retained profile exactly.')
        migration = EmbeddingMigration.objects.create(target=target, previous=previous, requested_by=actor,
                                                       auto_activate=auto_activate)
        audit(None, actor, 'embedding_migration_started', target_id=target.pk, migration_id=migration.pk, auto_activate=auto_activate)
        return migration


def coverage_guard(space):
    if pending(space).exists():
        raise ValidationError('Current eligible sources still lack vectors in this profile.')
    invalid = library_chunks().exclude(pk__in=verified_library_chunks().values('pk'))
    empty = library_versions().filter(chunks__isnull=True)
    if invalid.exists() or empty.exists():
        LibraryVersion.objects.filter(Q(pk__in=invalid.values('version_id')) | Q(pk__in=empty.values('pk'))).update(processing_state='failed', safe_error_code='LIBRARY_SOURCE_INVALID')
        raise EmbeddingFailure('LIBRARY_SOURCE_INVALID')


def activate_profile(space):
    with source_fence():
        coverage_guard(space)
        EmbeddingSpace.objects.filter(status='active').exclude(pk=space.pk).update(status='retired')
        space.status, space.activated_at = 'active', timezone.now()
        space.save(update_fields=['status', 'activated_at'])
    return space


def probe_profile(space, *, embedder=None):
    if space.provider != 'gemini':
        raise EmbeddingFailure('PROVIDER_NOT_SUPPORTED')
    from ai_workflows.harness.llm import get_embedder
    client = embedder or get_embedder(space=space)
    try:
        validate_vector(client.embed_query('Semantic index health check', output_dimensionality=space.dimensions), space.dimensions)
    finally:
        if embedder is None and hasattr(client, 'close'):
            client.close()


def preflight(migration, *, embedder=None):
    """Validate the endpoint/model on fixed text before sending any corpus data."""
    migration.refresh_from_db()
    if migration.status not in {'building', 'ready'} or migration.next_validation_at > timezone.now():
        return False
    try:
        probe_profile(migration.target, embedder=embedder)
    except Exception as exc:
        failure = classify_failure(exc)
        with source_fence():
            migration.refresh_from_db()
            if migration.status not in {'building', 'ready'}:
                return False
            migration.validation_attempts += 1
            migration.error_code = failure.code
            migration.next_validation_at = timezone.now() + timedelta(seconds=max(30 * 2 ** min(migration.validation_attempts, 5), failure.retry_after))
            migration.status = 'building' if failure.retryable and migration.validation_attempts < MAX_ATTEMPTS else 'blocked'
            migration.save()
        return False
    with source_fence():
        migration.refresh_from_db()
        if migration.status not in {'building', 'ready'}:
            return False
        EmbeddingSpace.objects.filter(pk=migration.target_id).update(needs_attention=False, retry_after=None, consecutive_failures=0, last_error_code='')
        migration.preflight_passed = True
        migration.validation_attempts = 0
        migration.error_code = ''
        migration.save(update_fields=['preflight_passed', 'validation_attempts', 'error_code', 'updated_at'])
    return True


def validate_migration(migration, *, embedder=None):
    migration.refresh_from_db()
    if migration.status not in {'building', 'ready'} or migration.next_validation_at > timezone.now():
        return
    if pending(migration.target).exists():
        return
    if not migration.preflight_passed and not preflight(migration, embedder=embedder):
        return
    if migration.status == 'ready' and not migration.auto_activate:
        return
    try:
        coverage_guard(migration.target)
        probe_profile(migration.target, embedder=embedder)
        from . import indexes
        if indexes.can_index(migration.target):
            indexes.ensure_index(migration.target)
            if not indexes.index_exists(migration.target):
                raise EmbeddingFailure('VECTOR_INDEX_UNAVAILABLE')
        with source_fence():
            migration.refresh_from_db()
            if migration.status not in {'building', 'ready'}:
                return
            coverage_guard(migration.target)
            migration.status, migration.error_code = 'ready', ''
            if migration.auto_activate:
                activate_profile(migration.target)
                migration.status, migration.active_slot = 'active', None
                audit(None, migration.requested_by, 'embedding_profile_activated', target_id=migration.target_id, migration_id=migration.pk)
            migration.save()
    except ValidationError:
        # Source writes during validation are ordinary reconciliation, not failures.
        return
    except Exception as exc:
        failure = classify_failure(exc)
        with source_fence():
            migration.refresh_from_db()
            if migration.status not in {'building', 'ready'}:
                return
            migration.validation_attempts += 1
            migration.error_code = failure.code
            migration.status = 'building' if failure.retryable and migration.validation_attempts < MAX_ATTEMPTS else 'blocked'
            migration.next_validation_at = timezone.now() + timedelta(seconds=max(failure.retry_after, min(3600, 30 * 2 ** migration.validation_attempts)))
            migration.save()
        logger.warning('Embedding profile validation failed: migration=%s code=%s', migration.pk, failure.code)


def tick(*, dispatch=True, validate=True, limit=100):
    """Bounded periodic reconciler; authoritative progress lives in DB, not broker."""
    now = timezone.now()
    EmbeddingWork.objects.filter(status='running', started_at__lt=now-timedelta(seconds=LEASE_SECONDS)).update(
        status='retry', error_code='WORKER_INTERRUPTED', next_attempt_at=now, lease_token=uuid.uuid4(), updated_at=now)
    migration = EmbeddingMigration.objects.filter(active_slot=1).select_related('target').first()
    spaces = list(EmbeddingSpace.objects.filter(status='active'))
    if migration and migration.status in {'building', 'ready'} and not migration.preflight_passed and validate:
        preflight(migration)
        migration.refresh_from_db()
    if migration and migration.status in {'building', 'ready'} and migration.preflight_passed:
        spaces.append(migration.target)
    for space in spaces:
        known = EmbeddingWork.objects.filter(space=space, document_id=OuterRef('pk'), source_hash=OuterRef('content_hash')).exclude(status__in=['cancelled', 'done'])
        for document in pending(space).annotate(work_exists=Exists(known)).filter(work_exists=False).order_by('pk')[:limit]:
            ensure_work(document, space)
        if migration and migration.target_id == space.pk and migration.status == 'ready' and pending(space).exists():
            EmbeddingMigration.objects.filter(pk=migration.pk, active_slot=1, status='ready').update(status='building', updated_at=timezone.now())
            migration.refresh_from_db()
    allowed = list(EmbeddingSpace.objects.filter(pk__in=[space.pk for space in spaces], needs_attention=False).filter(Q(retry_after=None) | Q(retry_after__lte=now)).values_list('pk', flat=True))
    due = EmbeddingWork.objects.filter(space_id__in=allowed, status__in=['queued', 'retry'], next_attempt_at__lte=now).filter(
        Q(dispatched_at=None) | Q(dispatched_at__lt=now-timedelta(seconds=LEASE_SECONDS))).order_by('next_attempt_at', 'pk')[:limit]
    if dispatch:
        for pk in due.values_list('pk', flat=True):
            enqueue_work(pk)
    if migration and validate:
        validate_migration(migration)
    for version_id in library_versions().filter(processing_state__in=['processing', 'queued', 'failed']).values_list('pk', flat=True)[:limit]:
        with source_fence():
            _finish_initial(version_id)


def control(actor, migration_id, action):
    require_admin(actor)
    with source_fence():
        migration = EmbeddingMigration.objects.select_for_update().get(pk=migration_id)
        if migration.active_slot != 1:
            raise ValidationError('This migration is already finished. Start a new validated rollback if needed.')
        if action == 'pause':
            migration.status = 'paused'
        elif action in {'resume', 'retry', 'activate'}:
            migration.status, migration.error_code = 'building', ''
            migration.validation_attempts = 0
            migration.next_validation_at = timezone.now()
            if action == 'activate':
                migration.auto_activate = True
            if action == 'retry':
                migration.preflight_passed = False
                EmbeddingSpace.objects.filter(pk=migration.target_id).update(needs_attention=False, retry_after=None, consecutive_failures=0, last_error_code='')
                EmbeddingWork.objects.filter(space=migration.target, status__in=['blocked', 'exhausted', 'retry']).update(
                    status='queued', attempts=0, error_code='', next_attempt_at=timezone.now())
        elif action == 'cancel':
            migration.status, migration.active_slot = 'cancelled', None
            EmbeddingWork.objects.filter(space=migration.target).exclude(status='done').update(status='cancelled', lease_token=uuid.uuid4())
        else:
            raise ValidationError('Unknown migration action.')
        migration.save()
        audit(None, actor, 'embedding_migration_control', migration_id=migration.pk, operation=action)
    return migration
