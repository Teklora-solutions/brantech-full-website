"""Shared SQL authorization before search, ranking, counts or pagination."""
from django.db.models import Q, F
from knowledge_base.models import LibraryDocument, LibraryChunk
from .policy import LibraryPolicy


def visible_documents(actor):
    rows = LibraryDocument.objects.filter(is_deleted=False)
    if not actor or not actor.is_authenticated or not actor.is_active:
        return rows.none()
    if LibraryPolicy.is_administrator(actor):
        return rows
    allowed = Q(owner_id=actor.pk) | Q(grants__user_id=actor.pk) | Q(grants__group__in=actor.groups.all())
    if actor.is_staff:
        allowed |= Q(visibility='organisation')
    return rows.filter(allowed).distinct()


def eligible_chunks(actor=None, *, public=False):
    rows = LibraryChunk.objects.filter(
        version__document__is_deleted=False,
        version_id=F('version__document__current_version_id'),
        version__processing_state='ready', version__clearance_state='approved',
        version__classification='internal_standard', version__permitted_provider='gemini',
        version__upload_authority=True,
    ).select_related('version__document', 'memory_document')
    if public:
        return rows.filter(version__public_approval_state='approved')
    return rows.filter(version__document__in=visible_documents(actor))
