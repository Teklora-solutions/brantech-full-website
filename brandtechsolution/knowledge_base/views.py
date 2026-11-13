"""CSRF-protected staff document library. No anonymous originals or public listing."""
from functools import wraps
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from . import forms
from .models import LibraryDocument
from .library.access import visible_documents
from .library.contracts import LibraryAction
from .library.policy import LibraryPolicy
from .library.services import audit, authorize, mutate, upload_document
from .library.previews import PREVIEW_MIME, TEXT_LIMIT, PreviewUnavailable, docx_pdf


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
        'preview_supported': bool(document.current_version and document.current_version.detected_format in PREVIEW_MIME),
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
def preview(request, pk, version_id):
    document = get_object_or_404(visible_documents(request.user).select_related('current_version'), pk=pk)
    authorize(request.user, document, LibraryAction.DOWNLOAD)
    version = document.current_version
    if not version or version.pk != version_id or version.detected_format not in PREVIEW_MIME:
        raise Http404
    if not version.original or not version.original.storage.exists(version.original.name):
        raise Http404
    fmt = version.detected_format
    try:
        if fmt in {'txt', 'md'}:
            with version.original.open('rb') as original:
                data = original.read(TEXT_LIMIT + 1)
            response = render(request, 'knowledge_base/reader.html', {
                'text': data[:TEXT_LIMIT].decode('utf-8-sig', errors='replace'),
                'truncated': len(data) > TEXT_LIMIT,
                'download_url': reverse('library:download', args=[document.pk]),
            })
            response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox allow-downloads"
        else:
            if fmt == 'docx':
                converted = docx_pdf(version)
                # A conversion can take seconds: recheck revocation/replacement
                # before delivering its result, without holding a DB lock over I/O.
                actor = get_object_or_404(get_user_model(), pk=request.user.pk)
                if not actor.is_active or not actor.is_staff:
                    raise PermissionDenied
                fresh = get_object_or_404(visible_documents(actor), pk=pk, current_version_id=version_id)
                authorize(actor, fresh, LibraryAction.DOWNLOAD)
                original = converted.open('rb')
                filename = Path(version.original_filename).stem + '.pdf'
            else:
                original = version.original.open('rb')
                filename = version.original_filename
            response = FileResponse(original, as_attachment=False, filename=filename, content_type=PREVIEW_MIME[fmt])
            # Strict MIME + nosniff: never serve raw Office/HTML/SVG as active
            # application HTML. Avoid sandbox here: it disables native PDF plugins.
            response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'self'"
    except FileNotFoundError:
        raise Http404 from None
    except PreviewUnavailable as exc:
        response = render(request, 'knowledge_base/reader.html', {
            'error': str(exc), 'download_url': reverse('library:download', args=[document.pk]),
        }, status=503)
        response['Retry-After'] = '5'
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox allow-downloads"
    else:
        audit(document, request.user, 'preview', version, format=fmt)
    response['X-Frame-Options'] = 'SAMEORIGIN'
    response['Referrer-Policy'] = 'no-referrer'
    response['Cross-Origin-Resource-Policy'] = 'same-origin'
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
