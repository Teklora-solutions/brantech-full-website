"""Private task evidence endpoints, separate from the staff-wide task serializer."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from knowledge_base.library.policy import LibraryPolicy
from knowledge_base.library.services import upload_document, audit
from knowledge_base.models import LibraryDocument
from . import deliverables as services
from .models import TaskSubmission, TaskSubmissionAttachment


def submission_data(submission):
    attachments = []
    for attachment in submission.attachments.select_related('version__document'):
        version = attachment.version
        available = bool(version and not version.document.is_deleted and version.original
                         and version.original.storage.exists(version.original.name))
        attachments.append({
            'id': attachment.pk, 'available': available,
            'filename': version.original_filename if available else 'Evidence unavailable',
            'version_number': version.version_number if available else None,
            'download_url': f'/api/work/tasks/{submission.task_id}/deliverable-file/{attachment.pk}/' if available else None,
        })
    latest = services.current_submission(submission.assignment) if submission.assignment_id else None
    return {
        'id': submission.pk, 'assignment_id': submission.assignment_id,
        'submitter': submission.submitter.username if submission.submitter else 'Deleted account',
        'revision': submission.revision, 'note': submission.note, 'created_at': submission.created_at,
        'state': submission.review_state, 'current': bool(latest and latest.pk == submission.pk),
        'attachments': attachments,
        'reviews': [{'decision': r.decision, 'feedback': r.feedback, 'created_at': r.created_at,
                     'reviewer': r.reviewer.username if r.reviewer else 'Former reviewer'}
                    for r in submission.reviews.select_related('reviewer')],
    }


class TaskDeliverablesMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if self.action in {'deliverables', 'deliverable_upload', 'deliverable_documents', 'review_deliverable', 'deliverable_file'}:
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
        return response

    @action(detail=True, methods=['get', 'post'])
    def deliverables(self, request, pk=None):
        task = self.get_object()
        if request.method == 'POST':
            return Response(submission_data(services.submit(task.pk, request.user, request.data)), status=201)
        rows = TaskSubmission.objects.filter(task=task).select_related('submitter', 'assignment')
        if not services.is_reviewer(request.user):
            rows = rows.filter(submitter=request.user, assignment__user=request.user)
        # No counts/notes/filenames from other assignees leak to ordinary board readers.
        return Response([{**submission_data(row), 'mine': row.submitter_id == request.user.pk} for row in rows])

    @action(detail=True, methods=['post'], url_path='deliverable-upload')
    @transaction.atomic
    def deliverable_upload(self, request, pk=None):
        task = self._locked(pk)
        services.require_open(task)
        services.own_assignment(task, request.user)
        title = request.data.get('title', '')
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValidationError('Provide a document title of at most 300 characters.')
        authority = request.data.get('authority') in (True, 'true', 'on', '1')
        try:
            document = upload_document(request.user, request.FILES.get('original'), title=title.strip(), authority=authority)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({'id': document.pk, 'title': document.title,
                         'version_id': document.current_version_id, 'version_number': document.current_version.version_number}, status=201)

    @action(detail=True, methods=['get'], url_path='deliverable-documents')
    def deliverable_documents(self, request, pk=None):
        task = self.get_object()
        services.require_open(task)
        services.own_assignment(task, request.user)
        rows = LibraryDocument.objects.filter(is_deleted=False, current_version__isnull=False).select_related('current_version')
        if not LibraryPolicy.is_administrator(request.user):
            rows = rows.filter(owner=request.user)
        query = request.query_params.get('q', '').strip()[:200]
        if query:
            rows = rows.filter(title__icontains=query)
        page = Paginator(rows, 20).get_page(request.query_params.get('page'))
        return Response({'results': [{'id': d.pk, 'title': d.title, 'version_id': d.current_version_id,
                                     'version_number': d.current_version.version_number} for d in page],
                         'next_page': page.next_page_number() if page.has_next() else None})

    @action(detail=True, methods=['post'], url_path='review-deliverable')
    def review_deliverable(self, request, pk=None):
        task = self.get_object()
        return Response(submission_data(services.review(task.pk, request.user, request.data)))

    @action(detail=True, methods=['get'], url_path=r'deliverable-file/(?P<attachment_id>\d+)')
    def deliverable_file(self, request, pk=None, attachment_id=None):
        task = self.get_object()
        attachment = TaskSubmissionAttachment.objects.filter(pk=attachment_id, submission__task=task).select_related(
            'submission__assignment', 'version__document').first()
        if not attachment or not services.can_read_submission(request.user, attachment.submission):
            raise Http404
        version = attachment.version
        if not version or version.document.is_deleted:
            raise Http404
        try:
            original = version.original.open('rb')
        except FileNotFoundError:
            raise Http404 from None
        audit(version.document, request.user, 'task_evidence_download', version)
        response = FileResponse(original, as_attachment=True, filename=version.original_filename,
                                content_type='application/octet-stream')
        response['Content-Security-Policy'] = "default-src 'none'; sandbox"
        return response
