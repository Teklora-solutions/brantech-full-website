"""Commits and roadmaps from GitHub, applied to the task board.

Two inputs, one set of rules (docs/plans/2026-10-28-github-task-automation-plan.md):

- Commits. A message that says "Task #N" is linked to task N. One that reaches
  the default branch and either closes it ("Closes Task #N") or merges a
  branch named <type>/task-N-<slug> finishes it: every outstanding assignment
  is marked done, so the task moves to In review by the usual rule. Nothing
  here approves a task.
- Roadmaps. Each unchecked leaf item of an unfinished milestone becomes a task
  and waits in the backlog for assignment; a checked item finishes assigned work.

Both arrive by polling (poll_repository, on Celery Beat) and, if configured,
by GitHub's push webhook (tasks.webhooks). Processing is idempotent, so the
two can overlap freely.
"""

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List, Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from brand.repo_docs import parse_roadmap

from .activity import record
from .emails import notify_review_ready
from .models import Repository, Task, TaskAssignment, TaskCommit

logger = logging.getLogger(__name__)

TASK_REF = re.compile(r"\btask\s*#\s*(\d+)", re.IGNORECASE)
CLOSING_REF = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|complete[sd]?|done)\b\W{0,3}task\s*#\s*(\d+)",
    re.IGNORECASE,
)
# "Merge branch 'feat/task-42-slug'" from a local --no-ff merge, and
# "Merge pull request #7 from owner/feat/task-42-slug" from GitHub.
MERGE_REF = re.compile(
    r"^Merge (?:branch '|pull request #\d+ from [^/\s]+/)(?:[\w.-]+/)*task-(\d+)\b",
    re.IGNORECASE,
)

ROADMAP_PATHS = ("ROADMAP.md", "docs/ROADMAP.md")
DOCUMENTATION_PATHS = {"readme.md", "changelog.md", "roadmap.md", "docs/roadmap.md",
                       "license", "license.md", "license.txt", "licence", "lisence", "liscense"}
FIRST_POLL_WINDOW = timedelta(days=7)


@dataclass
class Commit:
    sha: str
    message: str
    author_login: str = ""
    url: str = ""
    committed_at: Optional[object] = None


def referenced_tasks(message):
    """(task ids named, task ids finished) by a commit message."""
    named = {int(n) for n in TASK_REF.findall(message or "")}
    finished = {int(n) for n in CLOSING_REF.findall(message or "")}
    merge = MERGE_REF.match((message or "").strip())
    if merge:
        finished.add(int(merge.group(1)))
    return named | finished, finished


def github_login(value):
    """A profile's GitHub field reduced to the login: people paste URLs."""
    value = (value or "").strip().rstrip("/")
    value = re.sub(r"^(?:https?://)?(?:www\.)?github\.com/", "", value, flags=re.IGNORECASE)
    return value.split("/")[0].lstrip("@").lower()


def staff_by_login():
    found = {}
    for user in User.objects.filter(is_staff=True, is_active=True).select_related("staff_profile"):
        profile = getattr(user, "staff_profile", None)
        login = github_login(profile.github_username) if profile else ""
        if login:
            found[login] = user
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Finishing
# ─────────────────────────────────────────────────────────────────────────────

def finish_task(task, actor, reason):
    """Mark every outstanding assignment done. Returns True if it moved the
    task into review. Call inside a transaction with the task row locked."""
    if task.status == Task.DONE:
        return False
    outstanding = TaskAssignment.objects.filter(task=task, completed_at__isnull=True).select_related("user")
    if not outstanding:
        return False
    now = timezone.now()
    names = []
    for assignment in outstanding:
        if task.delivery_requirement != 'standard':
            # Automation must not finish other people's shares of new strict tasks.
            if not actor or assignment.user_id != actor.pk:
                continue
        from .deliverables import validate_completion
        from rest_framework.exceptions import ValidationError
        try:
            validate_completion(assignment)
        except ValidationError:
            # Evidence is not ready: leave the assignment open, not a false completion.
            continue
        assignment.completed_at = now
        assignment.save(update_fields=["completed_at"])
        names.append(assignment.user.username)
    if not names:
        return False
    record(task, actor, "marked_done", f"{', '.join(names)} marked done: {reason}")
    if task.refresh_review_state() == Task.IN_REVIEW:
        record(task, None, "submitted", "Every assignee is finished")
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Commits
# ─────────────────────────────────────────────────────────────────────────────

def apply_commits(repository, commits: Iterable[Commit], on_default_branch):
    """Link commits to the tasks they name and finish the ones they close.

    Returns {"linked": n, "finished": [task ids]}.
    """
    logins = staff_by_login()
    linked, review = 0, []
    for commit in commits:
        named, finishing = referenced_tasks(commit.message)
        if not named:
            continue
        author = logins.get((commit.author_login or "").lower())
        who = author.username if author else (commit.author_login or "someone")
        lines = (commit.message or "").strip().splitlines()
        first_line = lines[0][:200] if lines else ""
        for task_id in sorted(named):
            with transaction.atomic():
                task = Task.objects.select_for_update().filter(pk=task_id).first()
                if task is None or (task.repository_id is not None and repository is not None
                                    and task.repository_id != repository.pk):
                    continue
                closes = on_default_branch and task_id in finishing
                row, created = TaskCommit.objects.get_or_create(
                    task=task, sha=commit.sha,
                    defaults={
                        "repository": repository, "message": commit.message or "",
                        "author_login": commit.author_login or "", "author": author,
                        "url": commit.url or "", "committed_at": commit.committed_at,
                        "on_default_branch": on_default_branch, "finishes": closes,
                    },
                )
                if created:
                    linked += 1
                    where = "" if on_default_branch else " (not merged yet)"
                    record(task, author, "commit", f"{who} pushed {commit.sha[:7]}{where}: {first_line}")
                    if task.repository_id is None and repository is not None:
                        task.repository = repository
                        task.save(update_fields=["repository", "updated_at"])
                elif on_default_branch and not row.on_default_branch:
                    # Seen on a feature branch first, now merged.
                    row.on_default_branch, row.finishes = True, closes
                    row.save(update_fields=["on_default_branch", "finishes"])
                elif row.on_default_branch:
                    # Already handled on the default branch: nothing new.
                    continue
                if closes and finish_task(task, author, f"commit {commit.sha[:7]} reached {repository or 'the default branch'}"):
                    review.append(task)
    for task in review:
        transaction.on_commit(lambda task=task: notify_review_ready(task))
    return {"linked": linked, "finished": [t.pk for t in review]}


# ─────────────────────────────────────────────────────────────────────────────
# Roadmaps
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(title):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title.lower())).strip()


def roadmap_items(text):
    """Leaf checkbox items: [{key, title, done, milestone, milestone_title,
    milestone_done, parent}]. A group heading with sub-items is not work."""
    items = []
    for milestone in parse_roadmap(text):
        tasks = milestone["tasks"]
        parents = []
        for i, item in enumerate(tasks):
            parents = [p for p in parents if p["depth"] < item["depth"]]
            has_children = i + 1 < len(tasks) and tasks[i + 1]["depth"] > item["depth"]
            if not has_children:
                items.append({
                    "key": f"{milestone['number']}:{_normalise(item['title'])}"[:255],
                    "title": item["title"],
                    "done": item["done"],
                    "milestone": milestone["number"],
                    "milestone_title": milestone["title"],
                    "milestone_done": milestone["done"],
                    "parent": parents[-1]["title"] if parents else "",
                })
            parents.append(item)
    return items


def _short_title(item):
    """The item's own words, cut at the first colon or full stop so a long
    roadmap line still reads as a task title."""
    head = re.split(r"(?<=\w)[:.](?:\s|$)", item["title"], maxsplit=1)[0].strip()
    head = re.sub(r"\s*\((?:docs|/)[^)]*\)\s*$", "", head)
    return (head or item["title"])[:200]


FRONTEND_WORDS = (
    "page", "ui", "ux", "template", "modal", "css", "tailwind", "filter", "filtering",
    "dashboard", "card", "badge", "button", "form", "public", "client-facing",
    "drawer", "expandable", "listing", "design", "theme", "mobile", "frontend",
)
BACKEND_WORDS = (
    "model", "schema", "api", "sync", "webhook", "migration", "database", "celery",
    "import", "scan", "discovery", "token", "backend", "django admin", "data",
    "integration", "linking", "queue", "endpoint",
)


def _words(text):
    return set(re.findall(r"[a-z][a-z+#.-]*", text.lower()))


def assignee_candidates():
    """Developers who take automatic work."""
    return (
        User.objects.filter(
            is_staff=True, is_active=True,
            staff_profile__is_onboarded=True, staff_profile__auto_assign=True,
        )
        .select_related("staff_profile")
        .annotate(load=Count(
            "task_assignments",
            filter=Q(task_assignments__completed_at__isnull=True) & ~Q(task_assignments__task__status=Task.DONE),
        ))
    )


def choose_assignee(text, candidates=None, extra_load=None):
    """The best developer for a piece of work, or None."""
    text_l = (text or "").lower()
    words = _words(text_l)
    front = any((w in words) if " " not in w else (w in text_l) for w in FRONTEND_WORDS)
    back = any((w in words) if " " not in w else (w in text_l) for w in BACKEND_WORDS)
    extra_load = extra_load or {}
    best, best_rank = None, None
    for user in candidates if candidates is not None else assignee_candidates():
        profile = user.staff_profile
        skills = [s for s in (profile.coding_languages or []) + (profile.frameworks or []) if s]
        if not skills or not profile.auto_assign or not user.is_active:
            continue  # Roadmap work is code; people without a technical profile are not picked.
        role = (profile.primary_role or "").lower()
        is_front = "front" in role or "full" in role
        is_back = "back" in role or "full" in role
        area = int(front and is_front) + int(back and is_back)
        skill_hits = sum(
            1 for s in skills
            if any(part and part in words for part in _words(s.split("/")[0]))
            and len(s) > 2
        )
        load = getattr(user, "load", 0) + extra_load.get(user.pk, 0)
        rank = (-area, -skill_hits, load, user.username)
        if best_rank is None or rank < best_rank:
            best, best_rank = user, rank
    return best


@transaction.atomic
def apply_roadmap(repository, text, actor=None):
    """Create, link and finish tasks from a roadmap.

    Returns {"created": [ids], "linked": [ids], "finished": [ids]}.
    """
    # Serialize roadmap imports for this repository across webhook and Beat workers.
    Repository.objects.select_for_update().get(pk=repository.pk)
    created, linked, review = [], [], []
    for item in roadmap_items(text):
        with transaction.atomic():
            task = Task.objects.select_for_update().filter(
                repository=repository, roadmap_key=item["key"]).first()
            title = _short_title(item)
            if task is None and not item["done"] and not item["milestone_done"]:
                task = Task.objects.select_for_update().filter(
                    repository__isnull=True, roadmap_key="", title__iexact=title,
                ).exclude(status=Task.DONE).first()
                if task is not None:
                    task.repository, task.roadmap_key = repository, item["key"]
                    task.source = Task.ROADMAP
                    task.save(update_fields=["repository", "roadmap_key", "source", "updated_at"])
                    record(task, actor, "edited", f"Linked to the {repository} roadmap")
                    linked.append(task.pk)
                    continue
                description = (
                    f"From the {repository} roadmap, Milestone {item['milestone']}: "
                    f"{item['milestone_title']}."
                    + (f"\nPart of: {item['parent']}." if item["parent"] else "")
                    + f"\n\n{item['title']}\n\nReference it in commits as \"Task #<id>\"; "
                    "merging a branch named feat/task-<id>-<slug>, or a commit saying "
                    "\"Closes Task #<id>\", sends it for review."
                )
                task = Task.objects.create(
                    title=title, description=description, source=Task.ROADMAP,
                    repository=repository, roadmap_key=item["key"], created_by=actor,
                )
                # The id is only known now; put it into the instructions.
                task.description = task.description.replace("<id>", str(task.pk))
                task.save(update_fields=["description"])
                record(task, actor, "created", f"Imported from the {repository} roadmap, awaiting assignment")
                created.append(task.pk)
            elif task is not None and item["done"] and not task.roadmap_checked:
                if finish_task(task, actor, f"ticked off in the {repository} roadmap"):
                    review.append(task)
            if task is not None and task.roadmap_checked != item["done"]:
                task.roadmap_checked = item["done"]
                task.save(update_fields=["roadmap_checked"])

    for task in review:
        transaction.on_commit(lambda task=task: notify_review_ready(task))
    return {"created": created, "linked": linked, "finished": [t.pk for t in review]}


DOCUMENTATION_FILES = ("README.md", "CHANGELOG.md", "ROADMAP.md", "LICENSE")


@transaction.atomic
def apply_documentation_audit(repository, audit):
    """One active repair task per document, with findings from the shared audit."""
    if audit.get("status") not in ("ok", "problems"):
        return {"created": [], "updated": [], "resolved": []}
    Repository.objects.select_for_update().get(pk=repository.pk)
    grouped = {name: [] for name in DOCUMENTATION_FILES}
    for problem in audit.get("problems", []):
        if problem.get("file") in grouped:
            grouped[problem["file"]].append(problem)
    created, updated, resolved = [], [], []
    for name, problems in grouped.items():
        key = "documentation:" + name
        task = Task.objects.select_for_update().filter(
            repository=repository, source=Task.DOCUMENTATION, roadmap_key=key,
        ).exclude(status=Task.DONE).first()
        if problems:
            description = (
                f"Documentation repair: {name} in {repository.full_name}.\n\n"
                + "\n\n".join(f"- {p['message']}\n  Fix: {p['fix']}" for p in problems)
                + "\n\nUpdate the document, then submit the work for review. The next document check will verify these findings."
            )
            if task is None:
                task = Task.objects.create(title=f"Update {name}", description=description,
                                           source=Task.DOCUMENTATION, repository=repository, roadmap_key=key)
                record(task, None, "created", f"Documentation issues found in {name}; awaiting assignment")
                created.append(task.pk)
            elif task.description != description or task.documentation_resolved:
                task.description = description
                task.documentation_resolved = False
                task.save(update_fields=["description", "documentation_resolved", "updated_at"])
                record(task, None, "edited", f"Updated document check findings for {name}")
                updated.append(task.pk)
        elif task is not None and not task.documentation_resolved:
            task.documentation_resolved = True
            task.save(update_fields=["documentation_resolved", "updated_at"])
            record(task, None, "edited", f"Document check passed for {name}")
            if finish_task(task, None, f"{name} passed its document checks"):
                transaction.on_commit(lambda task=task: notify_review_ready(task))
            resolved.append(task.pk)
    return {"created": created, "updated": updated, "resolved": resolved}


# ─────────────────────────────────────────────────────────────────────────────
# Polling
# ─────────────────────────────────────────────────────────────────────────────

def _client():
    from github import Github

    from brandtechsolution.config import config

    if not config.github_access_token:
        raise ValueError("GITHUB_ACCESS_TOKEN is not set.")
    return Github(config.github_access_token)


def fetch_roadmap(gh_repo):
    from github import GithubException

    for path in ROADMAP_PATHS:
        try:
            return gh_repo.get_contents(path, ref=gh_repo.default_branch).decoded_content.decode("utf-8")
        except GithubException as exc:
            if exc.status != 404:
                raise
            continue
    return None


def poll_repository(repository, client=None):
    """Read new default-branch commits and the roadmap from GitHub."""
    from brand.github_cache import blocked_until
    if blocked_until():
        return {"skipped": "GitHub rate limit backoff"}
    client = client or _client()
    started = timezone.now()
    gh_repo = client.get_repo(repository.full_name)
    if gh_repo.default_branch and gh_repo.default_branch != repository.default_branch:
        repository.default_branch = gh_repo.default_branch
    since = (repository.last_checked_at or started - FIRST_POLL_WINDOW) - timedelta(minutes=10)
    from brand.github_cache import (
        CONTENT_TTL, cached_document_audit, fresh, repository_revision, snapshot_for,
    )
    from github import GithubException

    content_revision = repository_revision(gh_repo)
    revision = f"{content_revision}:roadmap={int(repository.track_roadmap)}" if content_revision else ""
    if (revision and repository.last_processed_revision == revision
            and fresh(repository.last_checked_at, CONTENT_TTL)):
        Repository.objects.filter(pk=repository.pk).update(last_error="")
        return {"unchanged": True}
    row = snapshot_for(gh_repo)
    audit = cached_document_audit(gh_repo, row)
    if audit.get("status") == "unknown":
        raise RuntimeError("Repository document checks could not be completed; the next sync will retry.")
    documentation = apply_documentation_audit(repository, audit)
    commits = []
    try:
        fetched_commits = list(gh_repo.get_commits(sha=repository.default_branch, since=since))
    except GithubException as exc:
        if exc.status != 409 or not audit.get("empty_repo"):
            raise
        fetched_commits = []
    for c in fetched_commits:
        commits.append(Commit(
            sha=c.sha, message=c.commit.message,
            author_login=c.author.login if c.author else "",
            url=c.html_url, committed_at=c.commit.author.date if c.commit.author else None,
        ))
    result = {"documentation": documentation, "commits": apply_commits(repository, reversed(commits), on_default_branch=True)}
    if repository.track_roadmap:
        from brand.github_cache import roadmap_from_snapshot
        if row is not None:
            row.refresh_from_db(fields=["documents", "document_contents"])
        text = roadmap_from_snapshot(row) if row is not None else fetch_roadmap(gh_repo)
        result["roadmap"] = apply_roadmap(repository, text) if text else None
    repository.last_checked_at = started
    repository.last_processed_revision = revision
    repository.last_error = ""
    repository.save(update_fields=["default_branch", "last_checked_at", "last_processed_revision", "last_error"])
    return result


def discover_project_repositories(projects=None):
    """Reuse GitHub Manager's synced projects; never create public projects here."""
    from urllib.parse import urlparse
    from brand.models import Project

    if projects is None:
        projects = Project.objects.filter(is_github_synced=True, github_repo_id__isnull=False)
    found = []
    for project in projects:
        parsed = urlparse(project.github_url or "")
        name = parsed.path.strip("/").removesuffix(".git")
        if parsed.hostname != "github.com" or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
            logger.warning("Cannot import roadmap for project %s: invalid GitHub URL", project.pk)
            continue
        with transaction.atomic():
            repository = Repository.objects.filter(project=project).first()
            if repository is None:
                repository = Repository.objects.filter(full_name__iexact=name).first()
            if repository is None:
                repository = Repository.objects.create(full_name=name, project=project)
            elif repository.project_id != project.pk and repository.project_id is None:
                repository.project = project
                repository.save(update_fields=["project"])
            found.append(repository)
    return found


def queue_project_import(project):
    """Called after a GitHub Manager sync. Beat recovers from broker outages."""
    from .tasks import poll_repository_task

    for repository in discover_project_repositories([project]):
        def enqueue(repository_id=repository.pk):
            try:
                poll_repository_task.delay(repository_id)
            except Exception:
                logger.exception("Could not queue project roadmap import for repository %s; Beat will retry", repository_id)
        transaction.on_commit(enqueue)


def poll_all():
    discover_project_repositories()
    client = _client()
    results = {}
    for repository in Repository.objects.all():
        try:
            results[repository.full_name] = poll_repository(repository, client)
        except Exception as exc:  # One bad repository must not stop the rest.
            from brand.github_cache import record_failure
            message = record_failure(f"task-repository:{repository.pk}", exc, full_name=repository.full_name)
            if getattr(exc, "status", None) == 404:
                logger.warning("Repository %s not found on GitHub (404); check if repository was renamed or deleted", repository.full_name)
            else:
                logger.exception("Polling %s failed", repository.full_name)
            Repository.objects.filter(pk=repository.pk).update(last_error=message)
            results[repository.full_name] = {"error": message}
    return results


def commits_from_push(payload):
    """Commits in a GitHub push event payload."""
    found = []
    for c in payload.get("commits") or []:
        author = c.get("author") or {}
        found.append(Commit(
            sha=c.get("id", ""), message=c.get("message", ""),
            author_login=author.get("username") or "",
            url=c.get("url", ""), committed_at=parse_datetime(c.get("timestamp") or ""),
        ))
    return found


def push_touches_roadmap(payload):
    for c in payload.get("commits") or []:
        for key in ("added", "modified", "removed"):
            if any(path in ROADMAP_PATHS for path in c.get(key) or []):
                return True
    return False


def push_touches_documents(payload):
    return any(
        isinstance(path, str) and path.lower() in DOCUMENTATION_PATHS
        for commit in payload.get("commits") or []
        for key in ("added", "modified", "removed")
        for path in commit.get(key) or []
    )
