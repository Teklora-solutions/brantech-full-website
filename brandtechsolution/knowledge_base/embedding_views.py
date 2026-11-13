"""Staff administrator controls; credentials/provider responses never enter the UI."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from . import embedding_lifecycle as lifecycle
from .forms import EmbeddingProfileForm, EmbeddingControlForm
from .models import EmbeddingSpace, EmbeddingMigration, EmbeddingWork, LibraryVersion, MemoryDocument, KnowledgeDocument
from .library.services import audit
from .views import library_view, _library_context


@library_view
@require_http_methods(['GET', 'POST'])
def index(request):
    lifecycle.require_admin(request.user)
    form = EmbeddingProfileForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop('confirm_cost')
        try:
            lifecycle.start_migration(request.user, **data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, 'Migration requested. Background workers will build and validate the new profile; the old profile keeps serving.')
            return redirect('library:embeddings')
    active = EmbeddingSpace.active()
    migration = EmbeddingMigration.objects.filter(active_slot=1).select_related('target', 'previous').first()
    spaces = [space.pk for space in [active, migration.target if migration else None] if space]
    failures = EmbeddingWork.objects.filter(space_id__in=spaces, status__in=['retry', 'blocked', 'exhausted']).select_related('space', 'document').order_by('-updated_at', '-pk')
    total = lifecycle.sources().count()
    managed_knowledge = MemoryDocument.objects.filter(scope='knowledge_base', kind='knowledge_document',
        content_type=ContentType.objects.get_for_model(KnowledgeDocument)).values('object_id')
    remaining = lifecycle.pending(migration.target).count() if migration else 0
    return render(request, 'knowledge_base/embeddings.html', {
        **_library_context(request.user, 'embeddings'), 'form': form, 'active': active, 'migration': migration,
        'total_sources': total, 'remaining': remaining, 'completed': max(0, total-remaining),
        'progress_percent': int(100 * max(0, total-remaining) / total) if total else 100,
        'active_remaining': lifecycle.pending(active).count() if active else total,
        'work_counts': list(EmbeddingWork.objects.filter(space_id__in=spaces).values('status').annotate(count=Count('pk'))),
        'failures': Paginator(failures, 20).get_page(request.GET.get('page')),
        'extraction_failures': LibraryVersion.objects.filter(processing_state='failed', extraction_complete=False,
            document__is_deleted=False, document__current_version_id=F('pk')).count(),
        'retired': EmbeddingSpace.objects.filter(status='retired').order_by('-activated_at', '-pk')[:10],
        'history': EmbeddingMigration.objects.filter(active_slot=None).select_related('target').order_by('-pk')[:10],
        'legacy_unmanaged': KnowledgeDocument.objects.exclude(pk__in=managed_knowledge).count(),
        'version_failures': LibraryVersion.objects.filter(processing_state='failed', document__is_deleted=False,
            document__current_version_id=F('pk')).select_related('document').order_by('-pk')[:20],
    })


@library_view
@require_POST
def control(request):
    lifecycle.require_admin(request.user)
    form = EmbeddingControlForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Invalid embedding control request.')
        return redirect('library:embeddings')
    data = form.cleaned_data
    operation = data['operation']
    try:
        if operation == 'rollback':
            space = get_object_or_404(EmbeddingSpace, pk=data.get('space_id'), status='retired')
            lifecycle.start_migration(request.user, model=space.model_id.removeprefix('models/'), backend=space.resolved_backend,
                dimensions=space.dimensions, auto_activate=True, target=space)
        elif operation == 'retry_failed':
            with lifecycle.source_fence():
                space = get_object_or_404(EmbeddingSpace, pk=data.get('space_id'))
                allowed = space.status == 'active' or EmbeddingMigration.objects.filter(active_slot=1, target=space).exists()
                if not allowed:
                    raise ValidationError('Only the active or current migration profile can be retried.')
                EmbeddingSpace.objects.filter(pk=space.pk).update(needs_attention=False, retry_after=None, consecutive_failures=0, last_error_code='')
                EmbeddingWork.objects.filter(space=space, status__in=['blocked', 'retry', 'exhausted']).update(
                    status='queued', attempts=0, error_code='', next_attempt_at=timezone.now(), dispatched_at=None)
                audit(None, request.user, 'embedding_failures_retried', space_id=space.pk)
        else:
            migration = get_object_or_404(EmbeddingMigration, pk=data.get('migration_id'))
            lifecycle.control(request.user, migration.pk, operation)
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    else:
        messages.success(request, 'Embedding control saved. Background workers will reconcile remaining work.')
    return redirect('library:embeddings')
