"""CSRF-protected staff document library. No anonymous originals or public listing."""
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import forms
from .models import LibraryDocument
from .library.access import visible_documents
from .library.contracts import LibraryAction
from .library.policy import LibraryPolicy
from .library.services import audit, authorize, mutate, upload_document


STATUS_OPTIONS = [
    ('awaiting_clearance', 'Awaiting clearance'), ('queued', 'Queued'),
    ('processing', 'Processing'), ('ready', 'Ready'), ('failed', 'Failed'), ('blocked', 'Blocked'),
]


def _library_context(actor, section):
    """All displayed counts come from the same actor-filtered ACL queryset."""
    overview = visible_documents(actor).aggregate(
        total=Count('pk', distinct=True),
        ready=Count('pk', filter=Q(current_version__processing_state='ready'), distinct=True),
        awaiting=Count('pk', filter=Q(current_version__clearance_state='pending'), distinct=True),
        public_pending=Count('pk', filter=Q(current_version__public_approval_state='pending'), distinct=True),
    )
    return {'overview': overview, 'library_section': section,
            'is_library_admin': LibraryPolicy.is_administrator(actor)}


def _filter_documents(request, rows):
    query = request.GET.get('q', '').strip()[:200]
    status = request.GET.get('status', '')
    if status not in dict(STATUS_OPTIONS):
        status = ''
    if query:
        # Metadata and current ready text only; ACL is already constrained.
        rows = rows.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(
            current_version__processing_state='ready', current_version__chunks__text__icontains=query,
        )).distinct()
    if status:
        rows = rows.filter(current_version__processing_state=status)
    return rows, {'query': query, 'selected_status': status, 'status_options': STATUS_OPTIONS}


def library_view(view):
    @wraps(view)
    @never_cache
    @login_required(login_url='/login/')
    def wrapper(request, *args, **kwargs):
        if not request.user.is_active or not request.user.is_staff:
            raise PermissionDenied
        response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    return wrapper


@library_view
@require_GET
def index(request):
    rows = visible_documents(request.user).select_related('owner', 'current_version')
    rows, filters = _filter_documents(request, rows)
    page = Paginator(rows, 20).get_page(request.GET.get('page'))
    if LibraryPolicy.is_administrator(request.user):
        for document in page:
            audit(document, request.user, 'admin_list', document.current_version)
    return render(request, 'knowledge_base/index.html', {
        'page_obj': page, **filters, **_library_context(request.user, 'documents'),
    })


@library_view
@require_http_methods(['GET', 'POST'])
def upload(request):
    form = forms.UploadForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            document = upload_document(request.user, form.cleaned_data['original'], **{
                key: form.cleaned_data[key] for key in ['title', 'description', 'category', 'tags', 'authority']
            })
            messages.success(request, 'Document uploaded privately. Administrator processing clearance is required.')
            return redirect('library:detail', pk=document.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'knowledge_base/upload.html', {
        'form': form, **_library_context(request.user, 'upload'),
    })


@library_view
@require_GET
def detail(request, pk):
    document = get_object_or_404(visible_documents(request.user).select_related('current_version', 'owner'), pk=pk)
    if LibraryPolicy.is_administrator(request.user):
        audit(document, request.user, 'admin_view', document.current_version)
    allowed = lambda action: bool(LibraryPolicy.evaluate(request.user, document, action))
    return render(request, 'knowledge_base/detail.html', {
        'document': document, 'version': document.current_version,
        'can_edit': allowed(LibraryAction.EDIT), 'can_share': allowed(LibraryAction.SHARE),
        **_library_context(request.user, 'documents'),
        'metadata_form': forms.MetadataForm(instance=document, auto_id='metadata_%s'),
        'replacement_form': forms.ReplacementForm(auto_id='replacement_%s'),
        'sharing_form': forms.SharingForm(initial={'visibility': document.visibility}, auto_id='sharing_%s'),
        'clearance_form': forms.ClearanceForm(auto_id='clearance_%s'),
        'review_form': forms.ReviewForm(auto_id='review_%s'),
        'chunks': document.current_version.chunks.all() if document.current_version and document.current_version.processing_state == 'ready' else [],
        'grants': document.grants.select_related('user', 'group') if allowed(LibraryAction.SHARE) else [],
        'events': document.audit_events.select_related('actor').order_by('-created_at')[:30] if allowed(LibraryAction.SHARE) else [],
    })


@library_view
@require_GET
def download(request, pk):
    document = get_object_or_404(visible_documents(request.user).select_related('current_version'), pk=pk)
    authorize(request.user, document, LibraryAction.DOWNLOAD)
    version = document.current_version
    if not version:
        raise Http404
    try:
        original = version.original.open('rb')
    except FileNotFoundError:
        raise Http404 from None
    audit(document, request.user, 'download', version)
    response = FileResponse(original, as_attachment=True, filename=version.original_filename, content_type='application/octet-stream')
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@library_view
@require_GET
def review_queue(request):
    if not LibraryPolicy.is_administrator(request.user):
        raise PermissionDenied
    queue = request.GET.get('queue', 'clearance')
    rows = visible_documents(request.user).select_related('current_version', 'owner')
    if queue == 'public':
        rows = rows.filter(current_version__public_approval_state='pending')
    else:
        queue = 'clearance'
        rows = rows.filter(current_version__clearance_state='pending')
    rows, filters = _filter_documents(request, rows)
    return render(request, 'knowledge_base/index.html', {
        'page_obj': Paginator(rows, 20).get_page(request.GET.get('page')),
        'queue': queue, **filters, **_library_context(request.user, queue),
    })


@library_view
@require_http_methods(['POST'])
def action(request, pk, action):
    # Hide inaccessible document identities even for forged mutation requests.
    get_object_or_404(visible_documents(request.user), pk=pk)
    form_types = {
        'metadata': forms.MetadataForm, 'replace': forms.ReplacementForm,
        'share': forms.SharingForm, 'remove_grant': forms.GrantRemovalForm,
        'clear': forms.ClearanceForm, 'block': forms.ClearanceForm,
        'approve': forms.ReviewForm, 'reject': forms.ReviewForm, 'revoke': forms.ReviewForm,
    }
    form_type = form_types.get(action)
    form = form_type(request.POST, request.FILES) if form_type else None
    if form and not form.is_valid():
        messages.error(request, 'Invalid form: ' + ' '.join(str(error) for errors in form.errors.values() for error in errors))
        return redirect('library:detail', pk=pk)
    try:
        mutate(request.user, pk, request.POST.get('version_id'), action,
               data=form.cleaned_data if form else {}, upload=request.FILES.get('original'))
    except LibraryDocument.DoesNotExist:
        raise Http404 from None
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
        return redirect('library:detail', pk=pk)
    messages.success(request, 'Library change saved.')
    return redirect('library:index' if action == 'delete' else 'library:detail', **({} if action == 'delete' else {'pk': pk}))
