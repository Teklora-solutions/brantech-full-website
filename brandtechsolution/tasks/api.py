from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from staff.permissions import has_capability

from .activity import record
from .deliverable_api import TaskDeliverablesMixin
from .deliverables import validate_completion, reset_reviews
from .emails import notify_review_ready
from .models import Repository, Task, TaskActivity, TaskAssignment, TaskCommit
from .permissions import IsStaffMember
from .serializers import RepositorySerializer, TaskActivitySerializer, TaskSerializer

CAPABILITY = "manage_tasks"


class TaskPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _can_manage(user):
    return user.has_perm(f"staff.{CAPABILITY}")


class TaskViewSet(TaskDeliverablesMixin, viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    pagination_class = TaskPagination

    def get_permissions(self):
        """Read wide, write narrow.

        Everyone on staff can see the board and take part in their own work;
        only manage_tasks can create, assign, edit, delete, approve or send
        back. The per-action split lives here rather than in one permission
        class so that adding an action forces a deliberate choice.
        """
        managed = {
            "create", "update", "partial_update", "destroy", "approve", "reopen", "assign",
        }
        if self.action in managed:
            return [has_capability(CAPABILITY)()]
        return [IsStaffMember()]

    def _base_queryset(self):
        return Task.objects.select_related("created_by", "repository", "repository__project").prefetch_related(
            Prefetch(
                "assignments",
                queryset=TaskAssignment.objects.select_related("user"),
            ),
            "activity",
            Prefetch("commits", queryset=TaskCommit.objects.select_related("author")),
        )

    def get_queryset(self):
        queryset = self._base_queryset()

        # Filters apply to the board listing only. A detail route addresses
        # one known task, and letting ?status= or ?mine= narrow the lookup
        # there would turn a stray query string on an approve or comment
        # request into a 404 on a task that plainly exists.
        if self.action != "list":
            return queryset

        params = self.request.query_params

        status = params.get("status")
        if status in dict(Task.STATUS_CHOICES):
            queryset = queryset.filter(status=status)

        # "Open" in the UI means "not finished", which includes tasks sitting
        # in review. Without this a task would vanish from the default board
        # the moment it was submitted, and only administrators could find it.
        if params.get("active") == "1":
            queryset = queryset.exclude(status=Task.DONE)

        if params.get("mine") == "1":
            queryset = queryset.filter(assignments__user=self.request.user)

        if params.get("assignee"):
            queryset = queryset.filter(assignments__user_id=params["assignee"])

        backlog = Q(source__in=Task.IMPORTED_SOURCES, assignments__isnull=True, status=Task.OPEN, roadmap_checked=False, documentation_resolved=False)
        if params.get("workspace") == "backlog":
            queryset = queryset.filter(backlog)
        elif params.get("workspace") == "board":
            queryset = queryset.exclude(source__in=Task.IMPORTED_SOURCES, assignments__isnull=True)
        if params.get("repository"):
            try:
                repository_id = int(params["repository"])
            except (ValueError, TypeError):
                raise ValidationError({"repository": "Choose a valid project."})
            queryset = queryset.filter(repository_id=repository_id)

        search = (params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )

        # The assignment joins above can multiply rows once two filters both
        # traverse the M2M.
        return queryset.distinct()

    def perform_create(self, serializer):
        with transaction.atomic():
            task = serializer.save(created_by=self.request.user)
            who = ", ".join(a.user.username for a in task.assignments.all())
            record(
                task,
                self.request.user,
                "created",
                f"Created and assigned to {who}" if who else "Created, unassigned",
            )

    def perform_update(self, serializer):
        with transaction.atomic():
            # Serialize assignment edits with submission/completion transactions.
            serializer.instance = Task.objects.select_for_update().get(pk=serializer.instance.pk)
            # `before` may safely come off the prefetch cache - nothing has
            # changed yet. `after` may not, for the reason spelled out in
            # Task.refresh_review_state: the cache still holds the old list.
            before = {a.user_id for a in serializer.instance.assignments.all()}
            task = serializer.save()
            fresh = TaskAssignment.objects.filter(task=task).select_related("user")
            after = {a.user_id for a in fresh}

            record(task, self.request.user, "edited", "Updated the task details")

            if before != after:
                who = ", ".join(a.user.username for a in fresh)
                record(
                    task,
                    self.request.user,
                    "assignees_changed",
                    f"Assignees are now {who}" if who else "Nobody is assigned",
                )
                # Removing the last unfinished assignee can complete a task,
                # and adding someone to a task already in review must pull it
                # back. Both are handled by the same rule.
                if task.refresh_review_state() == Task.IN_REVIEW:
                    record(task, None, "submitted", "Every assignee is finished")
                    notify_review_ready(task, self.request)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Claim an unassigned backlog item without replacing another manager's work."""
        validator = TaskSerializer(data={"assignee_ids": request.data.get("assignee_ids", [])}, partial=True)
        validator.is_valid(raise_exception=True)
        users = validator.validated_data.get("assignee_ids", [])
        if not users:
            raise ValidationError({"assignee_ids": "Choose at least one person."})
        with transaction.atomic():
            task = self._locked(pk)
            if (task.source not in Task.IMPORTED_SOURCES or task.status != Task.OPEN
                    or task.roadmap_checked or task.documentation_resolved or task.assignments.exists()):
                return Response({"detail": "This task is no longer awaiting assignment. Refresh the backlog."}, status=409)
            TaskAssignment.objects.bulk_create([
                TaskAssignment(task=task, user_id=uid) for uid in sorted({user.pk for user in users})
            ])
            task.save(update_fields=["updated_at"])
            record(task, request.user, "assignees_changed", "Assigned to " + ", ".join(sorted(user.username for user in users)))
        return Response(self.get_serializer(self._fresh(task)).data)

    def _locked(self, pk):
        """Re-read the task under a row lock.

        Two assignees can finish at the same moment. Without the lock both
        transactions see one outstanding assignment, both write their own
        completion, and neither observes the other - so the task never leaves
        OPEN and no administrator is ever told it is ready.

        get_object_or_404, not .get(): a bare DoesNotExist escapes DRF's
        exception handler as a 500, so a stale link to a deleted task would
        read as a server fault rather than a missing page.
        """
        return get_object_or_404(Task.objects.select_for_update(), pk=pk)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        """Mark an assignee's own share finished."""
        return self._set_completion(request, pk, done=True)

    @action(detail=True, methods=["post"])
    def uncomplete(self, request, pk=None):
        """Take back a completion - "actually, I'm not done"."""
        return self._set_completion(request, pk, done=False)

    def _set_completion(self, request, pk, done):
        target_id = request.data.get("assignee_id") or request.user.id

        with transaction.atomic():
            task = self._locked(pk)

            # An approved task is closed. Reopening is an administrator's
            # decision, not something an assignee does by toggling their box.
            if task.status == Task.DONE:
                raise ValidationError(
                    "This task is already approved. Ask an administrator to "
                    "send it back if more work is needed."
                )

            if str(target_id) != str(request.user.id) and not _can_manage(request.user):
                raise PermissionDenied(
                    "You can only update your own part of a task."
                )

            assignment = task.assignments.filter(user_id=target_id).first()
            if assignment is None:
                raise ValidationError("That person is not assigned to this task.")

            if done:
                validate_completion(assignment)
            else:
                reset_reviews(task, request.user, 'Assignment reopened; submit a fresh revision.', assignment)
            already = assignment.completed_at is not None
            if already != done:
                assignment.completed_at = timezone.now() if done else None
                assignment.save(update_fields=["completed_at"])
                record(
                    task,
                    request.user,
                    "marked_done" if done else "marked_undone",
                    f"{assignment.user.username}'s part is "
                    f"{'done' if done else 'back in progress'}",
                )

            moved = task.refresh_review_state()
            if moved == Task.IN_REVIEW:
                record(task, None, "submitted", "Every assignee is finished")

        # Sent after the transaction commits: mailing about a submission that
        # then rolled back would be worse than not mailing at all.
        if moved == Task.IN_REVIEW:
            notify_review_ready(task, request)

        return Response(self.get_serializer(self._fresh(task)).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        with transaction.atomic():
            task = self._locked(pk)
            if task.status != Task.IN_REVIEW:
                raise ValidationError(
                    "Only a task that is waiting for review can be approved."
                )
            from knowledge_base.models import LibraryDocument
            list(LibraryDocument.objects.select_for_update().filter(
                versions__task_attachments__submission__assignment__task=task).order_by('pk'))
            assignments = list(task.assignments.select_related('user'))
            if not assignments or any(a.completed_at is None for a in assignments):
                raise ValidationError('Every current assignee must finish before approval.')
            for assignment in assignments:
                validate_completion(assignment, approval=True)
            task.status = Task.DONE
            task.closed_at = timezone.now()
            task.save(update_fields=["status", "closed_at", "updated_at"])
            note = (request.data.get("note") or "").strip()
            record(task, request.user, "approved", note or "Approved")
        return Response(self.get_serializer(self._fresh(task)).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        """Send a task back for more work.

        A reason is mandatory. The whole value of a review step is that the
        people who have to redo the work are told what was wrong with it.
        """
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError({"reason": "Say what still needs doing."})

        with transaction.atomic():
            task = self._locked(pk)
            if task.status == Task.OPEN:
                raise ValidationError("This task is already open.")

            # Every completion is cleared, not just the submission flag: the
            # task is going back to the whole group, and leaving people ticked
            # off would send it straight back into review on the next save.
            reset_reviews(task, request.user, reason)
            task.assignments.update(completed_at=None)
            task.status = Task.OPEN
            task.submitted_at = None
            task.closed_at = None
            task.save(
                update_fields=["status", "submitted_at", "closed_at", "updated_at"]
            )
            record(task, request.user, "reopened", reason)

        return Response(self.get_serializer(self._fresh(task)).data)

    @action(detail=True, methods=["get", "post"])
    def activity(self, request, pk=None):
        """The task's timeline, and the way to add a comment to it."""
        task = self.get_object()

        if request.method == "GET":
            return Response(
                TaskActivitySerializer(
                    task.activity.select_related("actor"), many=True
                ).data
            )

        body = (request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "Write something first."})
        entry = record(task, request.user, TaskActivity.COMMENT, body)
        return Response(TaskActivitySerializer(entry).data, status=201)

    def _fresh(self, task):
        """Re-read with the prefetches so the response shape matches
        list/retrieve rather than the bare locked row."""
        return self._base_queryset().get(pk=task.pk)


@api_view(["GET"])
@permission_classes([IsStaffMember])
def summary(request):
    """Counts for the sidebar badge.

    `needs_review` is only meaningful to someone who can act on it, so it is
    reported as 0 otherwise rather than teasing a number they cannot open.
    """
    mine = Task.objects.filter(
        assignments__user=request.user, assignments__completed_at__isnull=True
    ).exclude(status=Task.DONE)

    return Response({
        "my_open": mine.distinct().count(),
        "needs_review": (
            Task.objects.filter(status=Task.IN_REVIEW).count()
            if _can_manage(request.user)
            else 0
        ),
        # Counted across the whole board, not just this viewer's work: the
        # board is readable by everyone, and an overdue task nobody has
        # noticed is the thing worth surfacing.
        "overdue": (
            Task.objects.exclude(status=Task.DONE)
            .filter(due_date__lt=timezone.localdate())
            .count()
        ),
        "done": Task.objects.filter(status=Task.DONE).count(),
        "backlog": Task.objects.filter(source__in=Task.IMPORTED_SOURCES, documentation_resolved=False, assignments__isnull=True,
                                       status=Task.OPEN, roadmap_checked=False).count(),
        "can_manage": _can_manage(request.user),
    })


@api_view(["GET"])
@permission_classes([IsStaffMember])
def assignable(request):
    """Staff who can be given work, for the assign picker."""
    from .serializers import staff_queryset

    return Response([
        {"id": u.id, "username": u.username}
        for u in staff_queryset().order_by("username")
    ])


class RepositoryViewSet(viewsets.ModelViewSet):
    """Repositories whose commits and roadmap drive the board.

    manage_tasks only, reading included: the list is configuration, and
    adding one can import unassigned roadmap tasks on its next check.
    """

    serializer_class = RepositorySerializer
    queryset = Repository.objects.all()
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_permissions(self):
        return [has_capability(CAPABILITY)()]

    def perform_create(self, serializer):
        serializer.save(added_by=self.request.user)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """Read the repository now instead of waiting for the next poll."""
        from .github import poll_repository

        repository = self.get_object()
        try:
            result = poll_repository(repository)
        except Exception as exc:
            Repository.objects.filter(pk=repository.pk).update(last_error=str(exc)[:1000])
            return Response({"error": f"Could not read {repository.full_name} from GitHub: {exc}"}, status=502)
        repository.refresh_from_db()
        return Response({"repository": self.get_serializer(repository).data, "result": result})


@api_view(["GET"])
@permission_classes([IsStaffMember])
def backlog_projects(request):
    """Read-only import status and project filters, using the existing integration."""
    repositories = Repository.objects.select_related("project").annotate(
        awaiting=Count("tasks", filter=Q(tasks__source__in=Task.IMPORTED_SOURCES, tasks__documentation_resolved=False, tasks__assignments__isnull=True,
                                         tasks__status=Task.OPEN, tasks__roadmap_checked=False))
    ).order_by("project__title", "full_name")
    return Response([
        {"id": repo.pk, "title": repo.project.title if repo.project_id else repo.full_name,
         "full_name": repo.full_name, "awaiting": repo.awaiting,
         "last_checked_at": repo.last_checked_at, "has_error": bool(repo.last_error)}
        for repo in repositories
    ])
