from django.contrib.auth.models import Permission, User
from django.test import TestCase

from staff.capabilities import ALL_CAPABILITIES, CODENAMES


class CapabilityRegistryTest(TestCase):
    def test_registry_has_eighteen_capabilities(self):
        # Bumped from 11 when manage_tasks was added, from 12 when
        # receive_alerts was, from 13 for view_all_mail, from 14 for
        # manage_mail_limits; down to 12 when view_inbox, handle_inquiries and
        # view_all_mail were removed (staff.0020), up to 16 when they came
        # back with receive_inquiry_emails (staff.0021). The count is pinned so that adding a capability
        # is a deliberate act: a new codename has to be given a migration and
        # a place in a preset role, and this test is what stops that being
        # forgotten.
        # Library publication approval (staff.0027/0028) and developer API
        # keys (staff.0025/0026) bring the existing registry to eighteen.
        self.assertEqual(len(ALL_CAPABILITIES), 18)

    def test_codenames_are_unique(self):
        self.assertEqual(len(CODENAMES), len(set(CODENAMES)))


class CapabilityPermissionsExistTest(TestCase):
    """post_migrate must have created one auth_permission row per capability."""

    def test_every_capability_has_a_permission_row(self):
        for codename in CODENAMES:
            with self.subTest(codename=codename):
                self.assertTrue(
                    Permission.objects.filter(
                        codename=codename, content_type__app_label="staff"
                    ).exists(),
                    f"No permission row for staff.{codename}",
                )

    def test_no_crud_permissions_were_generated(self):
        """default_permissions = () must suppress add/change/delete/view."""
        generated = Permission.objects.filter(
            content_type__app_label="staff"
        ).values_list("codename", flat=True)
        self.assertEqual(sorted(generated), sorted(CODENAMES))

    def test_permissions_are_checkable_on_a_user(self):
        user = User.objects.create_user("u", password="p", is_staff=True)
        user.user_permissions.add(
            Permission.objects.get(
                codename="send_campaigns", content_type__app_label="staff"
            )
        )
        user = User.objects.get(pk=user.pk)  # drop the permission cache
        self.assertTrue(user.has_perm("staff.send_campaigns"))
        self.assertFalse(user.has_perm("staff.manage_staff"))

    def test_superuser_has_every_capability(self):
        root = User.objects.create_superuser("root", password="p")
        for codename in CODENAMES:
            with self.subTest(codename=codename):
                self.assertTrue(root.has_perm(f"staff.{codename}"))
