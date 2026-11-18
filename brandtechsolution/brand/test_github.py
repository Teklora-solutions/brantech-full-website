"""The GitHub integration: repository import, the hourly re-sync, and the
admin endpoints that drive them.

GitHub itself is faked. `Github` is patched where github_service imports it,
so no test needs a token or a network, and the fake repo carries only the
attributes the service reads.
"""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from github.GithubException import GithubException

from brand.models import Project
from brandtechsolution.config import config
from staff.models import StaffProfile
from staff.tests.helpers import onboarded


def fake_repo(repo_id=101, name="widget", description="A widget.", commits=3,
              readme="# Widget", owner="teklora", permissions=None, is_auth_repo=True, private=True):
    commit_list = [
        SimpleNamespace(
            sha=f"{i:040x}",
            commit=SimpleNamespace(
                message=f"commit {i}\n\nbody",
                author=SimpleNamespace(name="dev", date=datetime(2026, 1, 1, tzinfo=dt_timezone.utc)),
            ),
            stats=SimpleNamespace(total=2, additions=1, deletions=1),
        )
        for i in range(commits)
    ]
    paginated = mock.MagicMock()
    paginated.totalCount = commits
    paginated.__getitem__.side_effect = lambda s: commit_list[s]
    repo = mock.MagicMock()
    repo.id = repo_id
    repo.name = name
    repo.full_name = f"{owner}/{name}"
    repo.default_branch = "main"
    repo.pushed_at = timezone.now() - timedelta(days=7)
    repo.description = description
    repo.html_url = f"https://github.com/{owner}/{name}"
    repo.private = private
    repo.owner.login = owner
    repo.permissions = permissions
    repo._is_auth_repo = is_auth_repo
    # The old code stored this as last_synced_at; a week ago makes the
    # difference visible.
    repo.updated_at = timezone.now() - timedelta(days=7)
    repo.get_commits.return_value = paginated
    repo.get_readme.return_value.decoded_content = readme.encode()
    return repo


class GitHubTestCase(TestCase):
    def setUp(self):
        queue = mock.patch("brand.github_cache.enqueue_refresh_job")
        queue.start()
        self.addCleanup(queue.stop)
        self.repos = {}
        self.staff_users = {}
        client = mock.MagicMock()
        client.get_repo.side_effect = lambda rid: self.repos[rid]

        def get_user_mock(login=None):
            if login is None:
                auth_user = mock.MagicMock()
                auth_user.get_repos.side_effect = lambda **kw: [
                    r for r in self.repos.values()
                    if getattr(r, '_is_auth_repo', True)
                ]
                return auth_user
            if login in self.staff_users:
                return self.staff_users[login]
            staff_mock = mock.MagicMock()
            staff_mock.get_repos.side_effect = lambda **kw: [
                r for r in self.repos.values()
                if r.owner.login == login
            ]
            return staff_mock

        client.get_user.side_effect = get_user_mock
        patches = [
            mock.patch("brand.github_service.Github", return_value=client),
            mock.patch.object(config, "github_access_token", "test-token"),
            mock.patch.object(config, "github_username", "teklora"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def add(self, **kw):
        repo = fake_repo(**kw)
        self.repos[repo.id] = repo
        return repo

    def sync(self, *ids):
        from brand.github_service import GitHubService
        return GitHubService().sync_repositories(list(ids))


class SyncTests(GitHubTestCase):
    def test_a_new_repo_becomes_a_project(self):
        self.add()
        result = self.sync(101)

        self.assertEqual(result["synced_count"], 1)
        p = Project.objects.get(github_repo_id=101)
        self.assertEqual(p.title, "widget")
        self.assertEqual(p.description, "A widget.")
        self.assertTrue(p.is_github_synced)
        self.assertEqual(p.github_role, "owner")
        self.assertEqual(p.commit_count, 3)
        self.assertEqual(p.readme_content, "# Widget")
        self.assertEqual(len(p.cached_commits), 3)
        self.assertEqual(p.cached_commits[0]["message"], "commit 0")

    def test_a_resync_keeps_edited_text_and_refreshes_the_facts(self):
        repo = self.add()
        self.sync(101)
        Project.objects.filter(github_repo_id=101).update(
            title="Widget Pro", short_description="Edited.", description="Edited in admin.",
        )

        repo.pushed_at = timezone.now()
        repo.name = "widget-renamed"
        repo.description = "GitHub's new blurb."
        repo.get_readme.return_value.decoded_content = b"# New readme"
        repo.get_commits.return_value.totalCount = 9
        self.sync(101)

        p = Project.objects.get(github_repo_id=101)
        self.assertEqual(p.title, "Widget Pro")
        self.assertEqual(p.short_description, "Edited.")
        self.assertEqual(p.description, "Edited in admin.")
        self.assertEqual(p.readme_content, "# New readme")
        self.assertEqual(p.commit_count, 9)

    def test_last_synced_at_is_when_we_synced_not_when_the_repo_changed(self):
        self.add()
        before = timezone.now()
        self.sync(101)
        self.assertGreaterEqual(Project.objects.get(github_repo_id=101).last_synced_at, before)

    def test_a_long_description_is_cut_to_fit(self):
        self.add(description="x" * 800)
        self.sync(101)
        self.assertEqual(len(Project.objects.get(github_repo_id=101).short_description), 500)

    def test_a_collaborator_repo_is_labelled_so(self):
        self.add(owner="someone-else")
        self.sync(101)
        self.assertEqual(Project.objects.get(github_repo_id=101).github_role, "collaborator")

    def test_a_staff_repo_is_labelled_so(self):
        staff_user = User.objects.create_user("staff-ann", password="p", first_name="Ann", last_name="Wanjiru")
        StaffProfile.objects.create(user=staff_user, github_username="annwanjiru")
        self.add(owner="annwanjiru")
        self.sync(101)
        self.assertEqual(Project.objects.get(github_repo_id=101).github_role, "staff")

    def test_the_command_resyncs_only_linked_projects(self):
        self.add()
        self.add(repo_id=202, name="other")
        self.sync(101)

        call_command("sync_github", verbosity=0)

        self.assertEqual(self.repos[101].get_readme.call_count, 1)
        self.assertEqual(self.repos[202].get_readme.call_count, 0)
        self.assertFalse(Project.objects.filter(github_repo_id=202).exists())


def staff_with(*codenames):
    user = onboarded(User.objects.create_user(f"staff-{'-'.join(codenames) or 'none'}", password="p", is_staff=True))
    user.user_permissions.add(*Permission.objects.filter(
        codename__in=codenames, content_type__app_label="staff",
    ))
    return User.objects.get(pk=user.pk)


class EndpointTests(GitHubTestCase):
    def test_the_list_marks_synced_repos(self):
        self.add()
        self.add(repo_id=202, name="other")
        self.sync(101)
        self.client.force_login(staff_with("manage_projects"))

        from brand.github_service import GitHubService
        GitHubService().get_user_repositories()
        resp = self.client.get("/api/github/repos/")

        self.assertEqual(resp.status_code, 200)
        synced = {r["id"]: r["is_synced"] for r in resp.json()["results"]}
        self.assertEqual(synced, {101: True, 202: False})

    def test_sync_endpoint_imports_the_selected_repos(self):
        self.add()
        self.client.force_login(staff_with("manage_projects"))

        resp = self.client.post("/api/github/sync/", json.dumps({"repo_ids": [101]}),
                                content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Project.objects.filter(github_repo_id=101).exists())

    def test_staff_without_manage_projects_is_refused(self):
        self.add()
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/github/repos/").status_code, 403)
        resp = self.client.post("/api/github/sync/", json.dumps({"repo_ids": [101]}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Project.objects.filter(github_repo_id=101).exists())

    def test_anonymous_gets_json_not_a_login_redirect(self):
        self.assertEqual(self.client.get("/api/github/repos/").status_code, 401)

    def test_non_numeric_ids_are_rejected(self):
        self.client.force_login(staff_with("manage_projects"))
        resp = self.client.post("/api/github/sync/", json.dumps({"repo_ids": ["abc"]}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_the_admin_panel_links_the_github_manager(self):
        self.client.force_login(staff_with("manage_projects"))
        page = self.client.get("/admin-panel/").content.decode()
        self.assertIn('id="nav-projects"', page)
        self.assertIn('id="projects"', page)
        self.assertIn("js/admin/github.js", page)

    def test_the_github_manager_is_hidden_without_manage_projects(self):
        self.client.force_login(staff_with("manage_blog"))
        page = self.client.get("/admin-panel/").content.decode()
        self.assertNotIn('id="nav-projects"', page)
        self.assertNotIn('id="projects"', page)

    def test_the_list_includes_project_data_for_synced_repos(self):
        self.add(repo_id=101, name="widget", description="A widget.")
        self.sync(101)
        self.client.force_login(staff_with("manage_projects"))

        from brand.github_service import GitHubService
        GitHubService().get_user_repositories()
        resp = self.client.get("/api/github/repos/")
        self.assertEqual(resp.status_code, 200)
        repo_data = resp.json()["results"][0]
        self.assertTrue(repo_data["is_synced"])
        self.assertIsNotNone(repo_data["project"])
        self.assertEqual(repo_data["project"]["title"], "widget")
        self.assertEqual(repo_data["project"]["commit_count"], 3)

    def test_github_repo_readme_endpoint(self):
        repo = self.add(repo_id=101, name="widget", readme="# Widget Readme")
        from brand.github_cache import refresh_content
        from brand.github_service import GitHubService
        refresh_content(GitHubService(), repo)
        self.client.force_login(staff_with("manage_projects"))

        resp = self.client.get("/api/github/repos/101/readme/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["readme"], "# Widget Readme")

    def test_staff_repositories_with_permissions_are_scanned_and_listed(self):
        staff_user = User.objects.create_user("staff-kevin", password="p", first_name="Kevin", last_name="Otieno")
        StaffProfile.objects.create(user=staff_user, github_username="kevin-dev", primary_role="Backend")

        # 1. Main authenticated repo
        self.add(repo_id=101, name="teklora-core", owner="teklora")

        # 2. Staff repo where our token has push/collaborator permissions
        self.add(
            repo_id=301,
            name="kevin-service",
            owner="kevin-dev",
            permissions=SimpleNamespace(admin=False, push=True, pull=True, maintain=False),
            is_auth_repo=False,
        )

        # 3. Staff public repo where we have NO push or admin permissions (only public pull)
        self.add(
            repo_id=302,
            name="kevin-hobby",
            owner="kevin-dev",
            permissions=SimpleNamespace(admin=False, push=False, pull=True, maintain=False),
            private=False,
            is_auth_repo=False,
        )

        # 4. Staff private repo where we have pull permissions
        self.add(
            repo_id=303,
            name="kevin-private-tool",
            owner="kevin-dev",
            permissions=SimpleNamespace(admin=False, push=False, pull=True, maintain=False),
            private=True,
            is_auth_repo=False,
        )

        self.client.force_login(staff_with("manage_projects"))
        from brand.github_service import GitHubService
        GitHubService().get_user_repositories()
        resp = self.client.get("/api/github/repos/")
        self.assertEqual(resp.status_code, 200)

        results = resp.json()["results"]
        result_ids = [r["id"] for r in results]

        # 101, 301, and 303 must be included; 302 (public without elevated perms) must be excluded
        self.assertIn(101, result_ids)
        self.assertIn(301, result_ids)
        self.assertIn(303, result_ids)
        self.assertNotIn(302, result_ids)

        staff_repo_301 = next(r for r in results if r["id"] == 301)
        self.assertEqual(staff_repo_301["role"], "staff")
        self.assertIsNotNone(staff_repo_301["staff_member"])
        self.assertEqual(staff_repo_301["staff_member"]["username"], "kevin-dev")
        self.assertEqual(staff_repo_301["staff_member"]["staff_name"], "Kevin Otieno")
        self.assertTrue(staff_repo_301["permissions"]["push"])

    def test_staff_repository_scan_handles_github_exception_gracefully(self):
        staff_user = User.objects.create_user("staff-ghost", password="p")
        StaffProfile.objects.create(user=staff_user, github_username="ghost-user")

        self.add(repo_id=101, name="core", owner="teklora")

        # Mock ghost-user to raise GithubException
        ghost_mock = mock.MagicMock()
        ghost_mock.get_repos.side_effect = GithubException(404, {"message": "User Not Found"}, {})
        self.staff_users["ghost-user"] = ghost_mock

        self.client.force_login(staff_with("manage_projects"))
        from brand.github_service import GitHubService
        GitHubService().get_user_repositories()
        resp = self.client.get("/api/github/repos/")
        self.assertEqual(resp.status_code, 200)

        results = resp.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], 101)
