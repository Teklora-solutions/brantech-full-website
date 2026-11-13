"""Assignment-specific document evidence and completion rules.

Task rows are locked before assignments, submissions, then library documents
(sorted by ID). No task-submission relationship grants ordinary library/AI access.
"""
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from knowledge_base.library.contracts import LibraryAction
from knowledge_base.library.policy import LibraryPolicy
from knowledge_base.library.services import audit
from knowledge_base.models import LibraryDocument, LibraryVersion
from .activity import record
from .models import Task, TaskAssignment, TaskSubmission, TaskSubmissionAttachment, TaskSubmissionReview


def is_reviewer(user):
    return bool(user.is_authenticated and user.is_active and user.is_staff and user.has_perm('staff.manage_tasks'))


def require_staff(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        raise PermissionDenied('Active staff membership is required.')


def current_submission(assignment):
    return TaskSubmission.objects.filter(assignment=assignment).order_by('-revision').first()


def evidence_available(submission):
    attachments = list(submission.attachments.select_related('version__document'))
    return bool(attachments) and all(
        a.version_id and not a.version.document.is_deleted
        and a.version.original and a.version.original.storage.exists(a.version.original.name)
        for a in attachments
    )


def has_code(assignment):
    return assignment.task.commits.filter(author_id=assignment.user_id, on_default_branch=True).exists()


def validate_completion(assignment, *, approval=False):
    """Shared by API/MCP, submission, approval and automation; no manager bypass."""
    submission = current_submission(assignment)
    if submission:
        if submission.review_state == 'changes_requested' or not evidence_available(submission):
            raise ValidationError('Submit a new revision with available document evidence first.')
        if approval and submission.review_state != 'accepted':
            raise ValidationError('Accept every current document submission before approving this task.')
    requirement = assignment.task.delivery_requirement
    if requirement == 'document' and not submission:
        raise ValidationError('Submit a document deliverable before marking your part complete.')
    if requirement == 'code' and not has_code(assignment):
        raise ValidationError('A default-branch commit attributed to this assignee is required.')
    if requirement == 'either' and not submission and not has_code(assignment):
        raise ValidationError('Submit a document or link an attributed default-branch commit first.')


def require_open(task):
    if task.status == Task.DONE:
        raise ValidationError('This task is approved. Ask an administrator to reopen it first.')


def own_assignment(task, actor):
    require_staff(actor)
    assignment = TaskAssignment.objects.filter(task=task, user=actor).first()
    if not assignment:
        raise PermissionDenied('Only a current assignee can submit work here.')
    return assignment


def notify_after_commit(task, actor, event, submitter=None):
    from .emails import notify_deliverable_event
    transaction.on_commit(lambda: notify_deliverable_event(task, actor, event, submitter))


@transaction.atomic
def submit(task_id, actor, data):
    require_staff(actor)
    task = Task.objects.select_for_update().get(pk=task_id)
    require_open(task)
    assignment = own_assignment(task, actor)
    try:
        request_id = UUID(str(data.get('request_id', '')))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({'request_id': 'Provide a valid submission retry ID.'})
    previous = TaskSubmission.objects.filter(request_id=request_id).first()
    if previous:
        if previous.assignment_id != assignment.pk:
            raise ValidationError('This retry ID belongs to another submission.')
        return previous
    latest = current_submission(assignment)
    if data.get('expected_submission_id') != (latest.pk if latest else None):
        raise ValidationError('Your submission changed. Reload the task before submitting.')
    if data.get('share_confirmation') is not True:
        raise ValidationError('Confirm sharing these versions with active task managers for review.')
    ids = data.get('version_ids')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(type(v) is not int or v <= 0 for v in ids) or len(set(ids)) != len(ids):
        raise ValidationError({'version_ids': 'Choose between 1 and 10 distinct document versions.'})
    note = data.get('note', '')
    if not isinstance(note, str) or len(note) > 5000:
        raise ValidationError({'note': 'Use a note of at most 5000 characters.'})
    versions = list(LibraryVersion.objects.filter(pk__in=ids).select_related('document'))
    if len(versions) != len(ids):
        raise ValidationError('One or more selected documents are unavailable.')
    documents = {d.pk: d for d in LibraryDocument.objects.select_for_update().filter(
        pk__in=[v.document_id for v in versions]).order_by('pk')}
    for version in versions:
        document = documents[version.document_id]
        if document.is_deleted or document.current_version_id != version.pk or not LibraryPolicy.evaluate(actor, document, LibraryAction.SHARE):
            raise ValidationError('A selected version changed or you no longer have sharing authority.')
        if not version.original or not version.original.storage.exists(version.original.name):
            raise ValidationError('A selected original is unavailable.')
    try:
        with transaction.atomic():
            submission = TaskSubmission.objects.create(
                task=task, assignment=assignment, submitter=actor,
                revision=latest.revision + 1 if latest else 1, request_id=request_id, note=note.strip(),
            )
    except IntegrityError as exc:
        # A retry UUID reused concurrently on a different task must not become a 500.
        raise ValidationError('Submission retry ID already used. Reload before submitting again.') from exc
    TaskSubmissionAttachment.objects.bulk_create([
        TaskSubmissionAttachment(submission=submission, version=version) for version in versions])
    validate_completion(assignment)
    for version in versions:
        audit(documents[version.document_id], actor, 'task_evidence_submitted', version,
              task_id=task.pk, submission_id=submission.pk, review_audience='active_manage_tasks')
    assignment.completed_at = timezone.now()
    assignment.save(update_fields=['completed_at'])
    # Board-wide activity deliberately has no filenames, notes or feedback.
    record(task, actor, 'marked_done', 'Submitted work for private review')
    task.refresh_review_state()
    notify_after_commit(task, actor, 'submitted')
    return submission


@transaction.atomic
def review(task_id, actor, data):
    if not is_reviewer(actor):
        raise PermissionDenied('Task management permission is required.')
    task = Task.objects.select_for_update().get(pk=task_id)
    require_open(task)
    submission_id = data.get('submission_id')
    if type(submission_id) is not int:
        raise ValidationError('Choose a valid submission.')
    submission = TaskSubmission.objects.filter(task=task, pk=submission_id).select_related('assignment').first()
    if not submission or not submission.assignment_id or current_submission(submission.assignment).pk != submission.pk:
        raise ValidationError('This submission is no longer current. Reload the task.')
    decision, feedback = data.get('decision'), data.get('feedback', '')
    if decision not in {'accepted', 'changes_requested'} or not isinstance(feedback, str) or len(feedback) > 5000:
        raise ValidationError('Choose a valid decision and feedback of at most 5000 characters.')
    if decision == 'changes_requested' and not feedback.strip():
        raise ValidationError('Explain what needs changing.')
    # Lock original documents against deletion during this review decision.
    list(LibraryDocument.objects.select_for_update().filter(
        versions__task_attachments__submission=submission).order_by('pk'))
    if decision == 'accepted':
        if not submission.assignment.completed_at or submission.review_state == 'changes_requested':
            raise ValidationError('The assignee must submit a new revision before acceptance.')
        if not evidence_available(submission):
            raise ValidationError('Submitted evidence is unavailable. Request a new revision.')
    if submission.review_state == decision:
        return submission
    TaskSubmissionReview.objects.create(submission=submission, reviewer=actor, decision=decision, feedback=feedback.strip())
    for attachment in submission.attachments.select_related('version__document'):
        if attachment.version_id and not attachment.version.document.is_deleted:
            audit(attachment.version.document, actor, 'task_evidence_reviewed', attachment.version,
                  task_id=task.pk, submission_id=submission.pk, decision=decision)
    if decision == 'changes_requested':
        submission.assignment.completed_at = None
        submission.assignment.save(update_fields=['completed_at'])
        task.refresh_review_state()
    record(task, actor, 'edited', 'Private deliverable review updated')
    notify_after_commit(task, actor, decision, submission.submitter)
    return submission


def reset_reviews(task, actor, feedback, assignment=None):
    """Whole-task reopen/undo keeps old decisions but requires fresh submission."""
    rows = TaskAssignment.objects.filter(task=task)
    if assignment:
        rows = rows.filter(pk=assignment.pk)
    for row in rows:
        submission = current_submission(row)
        if submission and submission.review_state != 'changes_requested':
            TaskSubmissionReview.objects.create(submission=submission, reviewer=actor,
                decision='changes_requested', feedback=feedback)


def can_read_submission(actor, submission):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff:
        return False
    return is_reviewer(actor) or bool(
        submission.submitter_id == actor.pk and submission.assignment_id
        and TaskAssignment.objects.filter(pk=submission.assignment_id, user=actor).exists()
    )
