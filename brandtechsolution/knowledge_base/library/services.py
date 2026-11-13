"""Locked library mutations, independent of HTML/API transport."""
import logging
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from knowledge_base.models import LibraryDocument, LibraryVersion, LibraryGrant, LibraryAudit
from .contracts import LibraryAction
from .parsers import validate_upload
from .policy import LibraryPolicy

logger = logging.getLogger(__name__)


def audit(document, actor, action, version=None, **details):
    return LibraryAudit.objects.create(document=document, version=version, actor=actor, action=action, details=details)


def authorize(actor, document, action):
    decision = LibraryPolicy.evaluate(actor, document, action)
    if not decision:
        raise PermissionDenied('This action is not permitted.')


def enqueue(version_id):
    """Broker failures leave an explicit retryable state, never a false success."""
    from knowledge_base.tasks import process_library_version
    try:
        process_library_version.delay(version_id)
    except Exception:
        LibraryVersion.objects.filter(pk=version_id, processing_state='queued').update(
            processing_state='failed', safe_error_code='QUEUE_UNAVAILABLE',
        )
        logger.warning('Library queue unavailable for version %s', version_id)


def _add_version(document, actor, upload, authority):
    if not authority:
        raise ValidationError('Confirm that you have authority to upload and process this document.')
    name, fmt, checksum = validate_upload(upload)
    number = (document.versions.order_by('-version_number').values_list('version_number', flat=True).first() or 0) + 1
    version = LibraryVersion(
        document=document, uploader=actor, version_number=number, original_filename=name,
        detected_format=fmt, size_bytes=upload.size, checksum_sha256=checksum, upload_authority=True,
    )
    version.original.save(name, upload, save=False)
    try:
        version.save()
    except Exception:
        version.original.delete(save=False)
        raise
    if document.current_version_id:
        LibraryVersion.objects.filter(pk=document.current_version_id).update(public_approval_state='revoked')
    document.current_version = version
    document.save()
    audit(document, actor, 'upload' if number == 1 else 'replace', version)
    return version


def upload_document(actor, upload, *, title, description='', category='general', tags=None, authority=False):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff:
        raise PermissionDenied('Active staff membership is required to upload.')
    # Validate before creating a document row.
    validate_upload(upload)
    with transaction.atomic():
        document = LibraryDocument.objects.create(owner=actor, title=title, description=description, category=category, tags=tags or [])
        _add_version(document, actor, upload, authority)
        return document


@transaction.atomic
def mutate(actor, document_id, expected_version_id, action, data=None, upload=None):
    data = data or {}
    document = LibraryDocument.objects.select_for_update().get(pk=document_id, is_deleted=False)
    version = document.current_version
    if not version or str(version.pk) != str(expected_version_id):
        raise ValidationError('The document changed. Reload before submitting again.')
    permissions = {
        'metadata': LibraryAction.EDIT, 'replace': LibraryAction.EDIT,
        'share': LibraryAction.SHARE, 'remove_grant': LibraryAction.SHARE,
        'delete': LibraryAction.DELETE, 'clear': LibraryAction.CLEAR_PROCESSING,
        'block': LibraryAction.CLEAR_PROCESSING, 'request_public': LibraryAction.SHARE,
        'approve': LibraryAction.APPROVE_PUBLIC, 'reject': LibraryAction.APPROVE_PUBLIC,
        'revoke': LibraryAction.REVOKE_PUBLIC, 'retry': LibraryAction.EDIT,
    }
    if action not in permissions:
        raise ValidationError('Unknown library action.')
    authorize(actor, document, permissions[action])
    details = {}
    if action == 'metadata':
        document.title = data['title']
        document.description = data.get('description', '')
        document.category = data.get('category', 'general')
        document.tags = data.get('tags', [])
        version.public_approval_state = 'revoked'
        document.save()
    elif action == 'replace':
        return _add_version(document, actor, upload, data.get('authority'))
    elif action == 'share':
        document.visibility = data['visibility']
        document.save()
        subject = data.get('user') or data.get('group')
        if subject:
            lookup = {'user': subject} if data.get('user') else {'group': subject}
            LibraryGrant.objects.update_or_create(document=document, **lookup, defaults={'access_level': data['access_level']})
            details = {'subject_type': next(iter(lookup)), 'subject_id': subject.pk, 'access_level': data['access_level']}
    elif action == 'remove_grant':
        document.grants.filter(pk=data['grant_id']).delete()
        details = {'grant_id': data['grant_id']}
    elif action == 'delete':
        document.is_deleted = True
        document.deleted_at = timezone.now()
        document.save()
        version.public_approval_state = 'revoked'
    elif action in {'clear', 'block'}:
        classification = data['classification']
        approved = action == 'clear' and classification == 'internal_standard' and version.upload_authority
        version.classification = classification
        version.permitted_provider = 'gemini' if approved else ''
        version.clearance_state = 'approved' if approved else 'rejected'
        version.processing_state = 'queued' if approved else 'blocked'
        version.public_approval_state = 'revoked'
        version.safe_error_code = '' if approved else 'PROCESSING_BLOCKED'
        version.attempts = 0
        version.processing_token = uuid.uuid4()
        details = {'classification': classification, 'provider': version.permitted_provider, 'reason': data['reason']}
        if approved:
            transaction.on_commit(lambda: enqueue(version.pk))
    elif action == 'retry':
        if version.clearance_state != 'approved' or version.processing_state != 'failed':
            raise ValidationError('Only failed, cleared documents may be retried.')
        version.processing_state = 'queued'
        version.safe_error_code = ''
        version.attempts = 0
        version.processing_token = uuid.uuid4()
        transaction.on_commit(lambda: enqueue(version.pk))
    elif action == 'request_public':
        if version.processing_state != 'ready' or version.clearance_state != 'approved':
            raise ValidationError('Processing must be ready before public review.')
        version.public_approval_state = 'pending'
    elif action in {'approve', 'reject', 'revoke'}:
        if action == 'approve' and (
            version.public_approval_state != 'pending' or version.processing_state != 'ready'
            or version.clearance_state != 'approved'
        ):
            raise ValidationError('Only ready, cleared versions awaiting public review can be approved.')
        version.public_approval_state = {'approve': 'approved', 'reject': 'rejected', 'revoke': 'revoked'}[action]
        details = {'reason': data['reason']}
    version.save()
    if action in {'clear', 'retry'} and version.clearance_state == 'approved':
        from knowledge_base.models import EmbeddingWork
        EmbeddingWork.objects.filter(document__library_chunk__version=version, space__status='active',
            status__in=['blocked', 'exhausted', 'retry', 'cancelled']).update(
            status='queued', attempts=0, error_code='', next_attempt_at=timezone.now(), dispatched_at=None)
    audit(document, actor, action, version, **details)
    return version
