import json

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.capabilities import CODENAMES
from staff.models import AuditEntry


def staff_with(*codenames, username="cap"):
    user = User.objects.create_user(username, password="p", is_staff=True)
    if codenames:
        user.user_permissions.add(
            *Permission.objects.filter(
                codename__in=codenames, content_type__app_label="staff"
            )
        )
    return User.objects.get(pk=user.pk)


class CapabilityListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/capabilities/").status_code, 403)

    def test_returns_the_grouped_registry(self):
        self.client.force_login(staff_with("manage_staff"))
        resp = self.client.get("/api/staff/capabilities/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([g["label"] for g in data],
                         ["Content", "Communications", "Administration", "Developer Tools"])
        flat = [c["codename"] for g in data for c in g["capabilities"]]
        # Derived from the registry rather than a second hardcoded count.
        # What this endpoint owes its caller is the WHOLE registry, grouped -
        # test_capabilities.CapabilityRegistryTest is where the count itself
        # is pinned, and duplicating the number here only meant two tests to
        # edit for one change.
        self.assertEqual(sorted(flat), sorted(CODENAMES))
        self.assertIn("send_campaigns", flat)


class RoleListTest(TestCase):
    def test_requires_manage_staff(self):
        self.client.force_login(staff_with())
        self.assertEqual(self.client.get("/api/staff/roles/").status_code, 403)

    def test_lists_presets_with_member_counts(self):
        user = staff_with("manage_staff")
        Group.objects.get(name="Editor").user_set.add(user)
        self.client.force_login(user)
        resp = self.client.get("/api/staff/roles/")
        self.assertEqual(resp.status_code, 200)
        by_name = {r["name"]: r for r in resp.json()["results"]}
        self.assertEqual(by_name["Editor"]["member_count"], 1)
        self.assertEqual(by_name["Marketing"]["member_count"], 0)
        self.assertIn("manage_blog", by_name["Editor"]["capabilities"])


class RoleWriteTest(TestCase):
    def setUp(self):
        # Also holds the capabilities these tests write into roles: adding a
        # capability to a role is a grant, and grants are restricted to what
        # the actor holds (see CapabilityGrantRestrictionTest). Mirrors the
        # same fixture fix in test_people_api.py's RoleAssignmentTest.
        self.admin = staff_with("manage_staff", "manage_blog", "manage_projects")
        self.client.force_login(self.admin)

    def test_create_a_role(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": ["manage_blog"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        group = Group.objects.get(name="Interns")
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["manage_blog"]
        )

    def test_create_writes_an_audit_entry(self):
        self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": []}),
            content_type="application/json",
        )
        entry = AuditEntry.objects.get(action="group_created")
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("Interns", entry.summary)

    def test_update_replaces_capabilities_and_records_before_after(self):
        group = Group.objects.get(name="Editor")
        resp = self.client.put(
            f"/api/staff/roles/{group.pk}/",
            json.dumps({"name": "Editor", "capabilities": ["manage_projects"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), ["manage_projects"]
        )
        entry = AuditEntry.objects.get(action="group_updated")
        self.assertIn("manage_blog", entry.detail["before"]["capabilities"])
        self.assertEqual(entry.detail["after"], {"capabilities": ["manage_projects"], "mailboxes": []})

    def test_unknown_capability_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Bad", "capabilities": ["not_a_capability"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Group.objects.filter(name="Bad").exists())

    def test_duplicate_name_is_rejected(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Editor", "capabilities": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_a_role(self):
        group = Group.objects.get(name="Support")
        resp = self.client.delete(f"/api/staff/roles/{group.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Group.objects.filter(name="Support").exists())
        self.assertTrue(AuditEntry.objects.filter(action="group_deleted").exists())

    def test_create_without_capabilities_key_is_a_clean_400(self):
        """Regression: missing `capabilities` on POST must raise DRF validation
        (400), not fall through to create()'s validated_data.pop("capabilities")
        KeyError, which DRF's exception handler does not catch and which
        surfaces as an unhandled 500."""
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Group.objects.filter(name="Interns").exists())

    def test_put_without_capabilities_key_is_rejected(self):
        """Regression: a full replace (PUT) omitting `capabilities` must not
        fail open and silently preserve the role's existing permissions -
        it should be rejected as a 400, same as any other missing required
        field on a non-partial update."""
        group = Group.objects.get(name="Editor")
        before = list(group.permissions.values_list("codename", flat=True))
        resp = self.client.put(
            f"/api/staff/roles/{group.pk}/",
            json.dumps({"name": "Editor"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        group.refresh_from_db()
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), before
        )

    def test_patch_without_capabilities_key_leaves_them_unchanged(self):
        """Guard against over-correction: PATCH is partial by design, so
        omitting `capabilities` must still succeed and leave the role's
        existing capabilities untouched."""
        group = Group.objects.get(name="Editor")
        before = list(group.permissions.values_list("codename", flat=True))
        resp = self.client.patch(
            f"/api/staff/roles/{group.pk}/",
            json.dumps({"name": "Senior Editor"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        group.refresh_from_db()
        self.assertEqual(group.name, "Senior Editor")
        self.assertEqual(
            list(group.permissions.values_list("codename", flat=True)), before
        )

    def test_create_response_includes_member_count(self):
        """Regression: create() built the Group via plain Group.objects.create(),
        bypassing the annotated get_queryset(), so member_count silently
        disappeared from the create response while list/retrieve/update kept it."""
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Interns", "capabilities": []}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["member_count"], 0)

    def test_read_still_returns_capabilities(self):
        """Regression guard for the write_only=True fix: capabilities must
        still appear in read responses via to_representation()'s override,
        proving write_only excludes the field from input defaulting/output
        machinery without removing it from the actual response body."""
        resp = self.client.get("/api/staff/roles/")
        self.assertEqual(resp.status_code, 200)
        by_name = {r["name"]: r for r in resp.json()["results"]}
        self.assertIn("manage_blog", by_name["Editor"]["capabilities"])


class CapabilityGrantRestrictionTest(TestCase):
    """A manage_staff holder must not be able to grant themselves the rest of
    the registry by editing a role they belong to.

    enforce_grantable_roles guards granting a ROLE to a PERSON; this guards
    adding a CAPABILITY to a ROLE, which reaches the same place.
    """

    def setUp(self):
        self.role = Group.objects.create(name="Office")
        self.role.permissions.set(
            Permission.objects.filter(
                codename="manage_staff", content_type__app_label="staff"
            )
        )
        self.actor = User.objects.create_user("office", password="p", is_staff=True)
        self.actor.groups.add(self.role)
        self.actor = User.objects.get(pk=self.actor.pk)
        self.client.force_login(self.actor)

    def _put(self, capabilities):
        return self.client.put(
            f"/api/staff/roles/{self.role.pk}/",
            json.dumps({"name": "Office", "capabilities": capabilities}),
            content_type="application/json",
        )

    def test_cannot_add_a_capability_the_actor_does_not_hold(self):
        resp = self._put(["manage_staff", "send_campaigns", "publish_blog"])
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            User.objects.get(pk=self.actor.pk).has_perm("staff.send_campaigns")
        )

    def test_cannot_create_a_role_carrying_capabilities_the_actor_lacks(self):
        resp = self.client.post(
            "/api/staff/roles/",
            json.dumps({"name": "Escalation", "capabilities": ["send_campaigns"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Group.objects.filter(name="Escalation").exists())

    def test_can_still_remove_a_capability(self):
        # De-escalation stays unrestricted.
        self.assertEqual(self._put([]).status_code, 200)
        self.assertEqual(list(self.role.permissions.all()), [])

    def test_a_superuser_is_exempt(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        self.assertEqual(self._put(["manage_staff", "send_campaigns"]).status_code, 200)


class NonCapabilityPermissionTest(TestCase):
    """An auth.Group can carry ANY Django permission, not just this app's
    capabilities. Groups made through /admin/ before this feature existed
    generally do.

    Treating the capability registry as the boundary left those permissions
    unrestricted, which was a path from manage_staff to is_superuser: grant a
    role carrying auth.change_user, accept it on an account you control, then
    tick is_superuser in /admin/, which exposes that field to any holder of
    change_user.
    """

    def setUp(self):
        self.legacy = Group.objects.create(name="LegacyOps")
        self.legacy.permissions.add(Permission.objects.get(codename="change_user"))
        self.actor = staff_with("manage_staff", username="actor")
        self.client.force_login(self.actor)
        self.victim = User.objects.create_user("victim", password="p", is_staff=True)

    def test_cannot_grant_a_role_carrying_a_permission_the_actor_lacks(self):
        resp = self.client.patch(
            f"/api/staff/people/{self.victim.pk}/",
            json.dumps({"role_ids": [self.legacy.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            User.objects.get(pk=self.victim.pk).has_perm("auth.change_user")
        )

    def test_cannot_invite_with_a_role_carrying_a_permission_the_actor_lacks(self):
        resp = self.client.post(
            "/api/staff/invitations/",
            json.dumps({"email": "new@example.com", "role_ids": [self.legacy.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_a_superuser_may_still_grant_it(self):
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.patch(
            f"/api/staff/people/{self.victim.pk}/",
            json.dumps({"role_ids": [self.legacy.pk]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_editing_a_role_preserves_its_non_capability_permissions(self):
        # The panel has no UI for ordinary Django permissions, so replacing
        # the whole set on every edit destroyed them silently - and the audit
        # entry recorded only the capability change.
        self.client.force_login(User.objects.create_superuser("root", password="p"))
        resp = self.client.put(
            f"/api/staff/roles/{self.legacy.pk}/",
            json.dumps({"name": "LegacyOps", "capabilities": ["manage_blog"]}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        codenames = set(self.legacy.permissions.values_list("codename", flat=True))
        self.assertIn("manage_blog", codenames)
        self.assertIn("change_user", codenames)
