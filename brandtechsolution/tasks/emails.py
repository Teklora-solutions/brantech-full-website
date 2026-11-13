import logging

from django.conf import settings
from brandtechsolution.mail import send_mail_each

from staff.emails import capability_holder_emails

logger = logging.getLogger(__name__)


def notify_review_ready(task, request=None):
    """Tell the administrators a task is waiting for review.

    Never raises. The panel's "Needs review" queue is the real signal and is
    derived from the task's status, so a mail server problem must not roll
    back the submission that a staff member has legitimately made.
    """
    recipients = capability_holder_emails("manage_tasks")
    if not recipients:
        return 0

    # Deep-links to the section rather than the panel's default Overview.
    # The version 2 shell reads ?section= on load, so this lands the reviewer
    # on the board instead of making them hunt for it from the dashboard.
    path = "/admin-panel/?section=tasks"
    url = request.build_absolute_uri(path) if request else path
    who = ", ".join(sorted(a.user.username for a in task.assignments.all()))

    try:
        send_mail_each(
            subject=f"[Teklora] Ready for review: {task.title}",
            message=(
                f"{who or 'Nobody'} finished work on \"{task.title}\".\n\n"
                f"Priority: {task.get_priority_display()}\n"
                f"Due: {task.due_date or 'no due date'}\n\n"
                f"Review it in the panel:\n{url}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        return len(recipients)
    except Exception:
        logger.exception("Could not send review notification for task %s", task.pk)
        return 0


def notify_deliverable_event(task, actor, event, submitter=None):
    """Private content stays in the permission-checked panel, never in email."""
    recipients = capability_holder_emails('manage_tasks') if event == 'submitted' else (
        [submitter.email] if submitter and submitter.is_active and submitter.is_staff and submitter.email else [])
    if not recipients:
        return 0
    try:
        send_mail_each(
            subject=f'[Teklora] Task #{task.pk}: deliverable {event.replace("_", " ")}',
            message=f'A task deliverable was {event.replace("_", " ")}. Sign in to Tasks to view the private submission and feedback.\n/admin-panel/?section=tasks',
            from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=recipients, fail_silently=False,
        )
        return len(recipients)
    except Exception:
        logger.exception('Could not send deliverable notification for task %s', task.pk)
        return 0
