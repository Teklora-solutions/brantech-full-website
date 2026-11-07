from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from staff.models import AuditEntry, DeveloperApiKey, StaffProfile
from tasks.models import Task, TaskAssignment


class DeveloperApiKeyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dev_jane",
            email="jane@teklora.co.ke",
            password="test-password-123",
            first_name="Jane",
            last_name="Doe",
            is_staff=True,
        )
        self.profile = StaffProfile.objects.create(
            user=self.user,
            primary_role="Fullstack Engineer",
            coding_languages=["Python", "TypeScript"],
        )
        # Grant generate_api_keys via Developer group
        self.dev_group = Group.objects.create(name="Developer")
        api_key_perm = Permission.objects.get(codename="generate_api_keys", content_type__app_label="staff")
        self.dev_group.permissions.add(api_key_perm)
        self.user.groups.add(self.dev_group)

        self.client.force_login(self.user)

    def test_model_generate_key_and_hashing(self):
        instance, raw_key = DeveloperApiKey.generate_key(self.user, "Claude Code - Test Laptop")
        self.assertTrue(raw_key.startswith("tkl_live_"))
        self.assertEqual(instance.name, "Claude Code - Test Laptop")
        self.assertTrue(instance.prefix.startswith("tkl_live_"))
        self.assertTrue(instance.is_active)

        # DB has hash, NOT plaintext
        self.assertNotEqual(instance.key_hash, raw_key)
        self.assertEqual(instance.key_hash, DeveloperApiKey.hash_key(raw_key))

        # String representation
        self.assertIn("Claude Code - Test Laptop", str(instance))
        self.assertIn(instance.prefix, str(instance))

        # Revocation
        instance.revoke()
        self.assertFalse(instance.is_active)

    def test_generate_and_list_keys_api_with_role(self):
        # 1. Generate key
        resp = self.client.post(
            "/api/staff/developer/keys/",
            {"name": "Claude Code - Test Laptop"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        raw_key = data["key"]
        self.assertTrue(raw_key.startswith("tkl_live_"))
        self.assertEqual(data["name"], "Claude Code - Test Laptop")
        self.assertTrue(data["prefix"].startswith("tkl_live_"))
        self.assertIn("/developer/setup/?key=tkl_live_", data["setup_url"])
        self.assertIn("Read instructions at", data["agent_prompt"])

        # DB has hash, NOT plaintext
        db_key = DeveloperApiKey.objects.get(pk=data["id"])
        self.assertNotEqual(db_key.key_hash, raw_key)
        self.assertEqual(db_key.key_hash, DeveloperApiKey.hash_key(raw_key))

        # Audit entry exists
        self.assertTrue(
            AuditEntry.objects.filter(action="api_key_created", actor=self.user).exists()
        )

        # 2. List keys
        list_resp = self.client.get("/api/staff/developer/keys/")
        self.assertEqual(list_resp.status_code, 200)
        keys_list = list_resp.json()
        self.assertEqual(len(keys_list), 1)
        self.assertNotIn("key", keys_list[0])  # Plaintext never returned in list
        self.assertEqual(keys_list[0]["prefix"], db_key.prefix)

        # 3. Revoke key
        revoke_resp = self.client.post(f"/api/staff/developer/keys/{db_key.pk}/revoke/")
        self.assertEqual(revoke_resp.status_code, 200)
        db_key.refresh_from_db()
        self.assertFalse(db_key.is_active)
        self.assertTrue(
            AuditEntry.objects.filter(action="api_key_revoked", actor=self.user).exists()
        )

    def test_cannot_generate_or_list_keys_without_role(self):
        # User without generate_api_keys capability
        unprivileged_user = User.objects.create_user(
            username="unprivileged_staff",
            email="unprivileged@teklora.co.ke",
            password="test-password-123",
            is_staff=True,
        )
        self.client.force_login(unprivileged_user)

        # Listing forbidden
        list_resp = self.client.get("/api/staff/developer/keys/")
        self.assertEqual(list_resp.status_code, 403)

        # Generating forbidden
        post_resp = self.client.post(
            "/api/staff/developer/keys/",
            {"name": "Attempt Key"},
            content_type="application/json",
        )
        self.assertEqual(post_resp.status_code, 403)

    def test_api_key_authentication_on_endpoints(self):
        instance, raw_key = DeveloperApiKey.generate_key(self.user, "Bearer Auth Key")

        # Sign out from session
        self.client.logout()

        # Without credentials: 403 / 401
        unauth_resp = self.client.get("/api/staff/me/")
        self.assertIn(unauth_resp.status_code, [401, 403])

        # With Bearer header
        auth_resp = self.client.get(
            "/api/staff/me/",
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        self.assertEqual(auth_resp.status_code, 200)
        self.assertEqual(auth_resp.json()["username"], "dev_jane")

        # With X-Teklora-Api-Key header
        x_auth_resp = self.client.get(
            "/api/staff/me/",
            HTTP_X_TEKLORA_API_KEY=raw_key,
        )
        self.assertEqual(x_auth_resp.status_code, 200)
        self.assertEqual(x_auth_resp.json()["username"], "dev_jane")

        # Verify last_used_at got updated
        instance.refresh_from_db()
        self.assertIsNotNone(instance.last_used_at)

    def test_revoked_key_fails_authentication(self):
        instance, raw_key = DeveloperApiKey.generate_key(self.user, "Revoke Auth Key")
        instance.revoke()

        self.client.logout()
        resp = self.client.get(
            "/api/staff/me/",
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        self.assertIn(resp.status_code, [401, 403])

    def test_developer_agent_setup_markdown_endpoint(self):
        resp = self.client.get("/developer/setup/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        content = resp.content.decode("utf-8")

        # 1. How to get the skills
        self.assertIn("Step 1: Install the Teklora Developer Skill", content)
        self.assertIn("/developer/skill/SKILL.md", content)

        # 2. MCP config
        self.assertIn("Step 2: Install and Configure the Teklora MCP Server", content)
        self.assertIn("teklora_mcp.py", content)
        self.assertIn("claude mcp add", content)

        # 3. How it will be receiving updates
        self.assertIn("Step 3: How to Receive Updates", content)
        self.assertIn("server.py", content)

        # 4. Guide user on how to get the API key and where to put it
        self.assertIn("Step 4: AGENT INSTRUCTION — Guide the User on Their API Key", content)
        self.assertIn("TEKLORA_API_KEY", content)
        self.assertIn("admin@teklora.co.ke", content)

    def test_developer_mcp_script_download(self):
        resp = self.client.get("/developer/mcp/server.py")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/x-python", resp["Content-Type"])
        self.assertIn("TekloraClient", resp.content.decode("utf-8"))

    def test_developer_skill_download(self):
        resp = self.client.get("/developer/skill/SKILL.md")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        content = resp.content.decode("utf-8")
        self.assertIn("name: teklora-developer", content)
        self.assertIn("Teklora Solutions", content)

    def test_mcp_server_client_and_tools(self):
        from scripts.teklora_mcp import TekloraClient, handle_tool_call

        instance, raw_key = DeveloperApiKey.generate_key(self.user, "MCP Test Key")
        task = Task.objects.create(
            id=101,
            title="Implement MCP endpoints",
            description="Complete developer MCP tools",
            created_by=self.user,
        )
        TaskAssignment.objects.create(task=task, user=self.user)

        # Test local client using Django test client adapter / direct mock
        class DirectTestClient(TekloraClient):
            def __init__(self, django_client, raw_key):
                super().__init__("http://testserver", raw_key)
                self.django_client = django_client

            def _request(self, method, path, data=None, params=None):
                headers = {"HTTP_AUTHORIZATION": f"Bearer {self.api_key}"}
                if method == "GET":
                    r = self.django_client.get(path, params or {}, **headers)
                elif method == "POST":
                    r = self.django_client.post(path, data or {}, content_type="application/json", **headers)
                else:
                    raise NotImplementedError
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.content}")
                return r.json()

        direct_client = DirectTestClient(self.client, raw_key)

        # Test profile tool
        profile_res = handle_tool_call(direct_client, "teklora_get_developer_profile", {})
        self.assertIn("dev_jane", profile_res)
        self.assertIn("Fullstack Engineer", profile_res)

        # Test task list tool
        task_list_res = handle_tool_call(direct_client, "teklora_list_my_tasks", {})
        self.assertIn("Task #101", task_list_res)
        self.assertIn("Implement MCP endpoints", task_list_res)

        # Test task details tool
        task_detail_res = handle_tool_call(direct_client, "teklora_get_task_details", {"task_id": 101})
        self.assertIn("Task #101", task_detail_res)
        self.assertIn("Complete developer MCP tools", task_detail_res)

        # Test complete assignment tool
        complete_res = handle_tool_call(direct_client, "teklora_complete_task_assignment", {"task_id": 101})
        self.assertIn("Successfully marked assignment completed", complete_res)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.IN_REVIEW)
