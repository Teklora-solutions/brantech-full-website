from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from staff.tests.helpers import onboarded


class TaskSectionVisibilityTest(TestCase):
    """The board is ungated; the controls on it are not.

    This is the one design decision most likely to be "tidied" later into a
    {% if can.manage_tasks %} wrapper to match the sections around it, which
    would hide their own work from every staff member who cannot assign it.
    """

    def test_section_renders_for_a_staff_member_with_no_capabilities(self):
        user = onboarded(User.objects.create_user("nobody", password="pw", is_staff=True))
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        self.assertContains(response, 'id="taskList"')
        self.assertNotContains(response, 'id="taskRepoForm"')
        self.assertContains(response, 'id="nav-tasks"')
        # So is mail: everyone has their own mailbox.
        self.assertContains(response, 'id="nav-inbox"')

    def test_manage_tasks_is_not_leaked_to_someone_without_it(self):
        user = onboarded(User.objects.create_user("nobody", password="pw", is_staff=True))
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        # The capability list drives the JS gate. Absent means the New task
        # button stays hidden - and the API refuses regardless.
        self.assertNotContains(response, "manage_tasks")

    def test_capability_is_advertised_to_a_holder(self):
        user = onboarded(User.objects.create_user("boss", password="pw", is_staff=True))
        group = Group.objects.create(name="Leads")
        group.permissions.add(
            Permission.objects.get(
                codename="manage_tasks", content_type__app_label="staff"
            )
        )
        user.groups.add(group)
        self.client.force_login(user)

        response = self.client.get("/admin-panel/")

        self.assertContains(response, "manage_tasks")
        self.assertNotContains(response, 'id="taskRepoForm"')
        self.assertContains(response, 'id="taskBacklogProject"')


class NavGatingTest(TestCase):
    """The sidebar and the sections it points at must agree.

    The version 2 redesign moved the nav into admin_base.html and dropped
    every {% if can.x %} gate on the way. admin_panel.html still gates each
    SECTION, so the result was links pointing at markup that is not in the
    DOM for the people who cannot use them - clicking one blanks the content
    area with no explanation. Restored during that merge; pinned here.
    """

    def _staff(self, *capabilities):
        user = onboarded(User.objects.create_user("u", password="pw", is_staff=True))
        if capabilities:
            group = Group.objects.create(name="role")
            group.permissions.set([
                Permission.objects.get(
                    codename=c, content_type__app_label="staff"
                )
                for c in capabilities
            ])
            user.groups.add(group)
        return user

    def test_links_are_hidden_for_sections_the_user_cannot_open(self):
        self.client.force_login(self._staff())

        response = self.client.get("/admin-panel/")

        self.assertNotContains(response, 'id="nav-blogs"')
        self.assertNotContains(response, 'id="nav-campaigns"')
        self.assertNotContains(response, 'id="nav-staff"')
        self.assertNotContains(response, 'id="nav-developer"')

    def test_links_appear_for_what_the_user_holds(self):
        self.client.force_login(self._staff("manage_blog", "manage_staff", "generate_api_keys"))

        response = self.client.get("/admin-panel/")

        self.assertContains(response, 'id="nav-blogs"')
        self.assertContains(response, 'id="nav-staff"')
        self.assertContains(response, 'id="nav-developer"')
        self.assertNotContains(response, 'id="nav-campaigns"')

    def test_tasks_link_is_ungated(self):
        """The one deliberate exception - everyone can open the board."""
        self.client.force_login(self._staff())

        response = self.client.get("/admin-panel/")

        self.assertContains(response, 'id="nav-tasks"')

    def test_shell_gets_capabilities_on_pages_that_only_extend_it(self):
        """appointments and editorial extend admin_base.html but their views
        never build the capability set. Without the context processor every
        gate reads false there and the whole sidebar renders empty."""
        self.client.force_login(self._staff("manage_appointments"))

        response = self.client.get("/appointments/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-tasks"')
        self.assertContains(response, 'id="nav-appointments"')


class PresetRoleTest(TestCase):
    def test_administrator_preset_can_assign_work(self):
        """0007 grants it. Without this the section ships dead for everyone
        holding the Administrator role rather than a superuser flag."""
        group = Group.objects.get(name="Administrator")

        self.assertTrue(
            group.permissions.filter(
                codename="manage_tasks", content_type__app_label="staff"
            ).exists()
        )

    def test_administrator_preset_can_generate_api_keys(self):
        group = Group.objects.get(name="Administrator")
        self.assertTrue(
            group.permissions.filter(
                codename="generate_api_keys", content_type__app_label="staff"
            ).exists()
        )

    def test_scoped_presets_are_left_alone(self):
        for name in ("Editor", "Marketing", "Support"):
            with self.subTest(role=name):
                group = Group.objects.get(name=name)
                self.assertFalse(
                    group.permissions.filter(codename="manage_tasks").exists()
                )
