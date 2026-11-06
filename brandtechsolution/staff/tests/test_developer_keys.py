from django.contrib.auth.models import User
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
        self.client.force_login(self.user)

    def test_generate_and_list_keys(self):
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

    def test_revoke_developer_key(self):
        instance, raw_key = DeveloperApiKey.generate_key(self.user, "Key to revoke")
        self.assertTrue(instance.is_active)

        resp = self.client.post(f"/api/staff/developer/keys/{instance.pk}/revoke/")
        self.assertEqual(resp.status_code, 200)

        instance.refresh_from_db()
        self.assertFalse(instance.is_active)
        self.assertTrue(
            AuditEntry.objects.filter(action="api_key_revoked", actor=self.user).exists()
        )

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
        instance, raw_key = DeveloperApiKey.generate_key(self.user, "Setup Key")

        # 1. With valid key in query param
        resp = self.client.get(f"/developer/setup/?key={raw_key}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        content = resp.content.decode("utf-8")
        self.assertIn("dev_jane", content)
        self.assertIn("Fullstack Engineer", content)
        self.assertIn(raw_key, content)
        self.assertIn("teklora_mcp.py", content)
        self.assertIn("claude mcp add", content)

        # 2. Without key
        anon_resp = self.client.get("/developer/setup/")
        self.assertEqual(anon_resp.status_code, 200)
        anon_content = anon_resp.content.decode("utf-8")
        self.assertIn("<YOUR_TEKLORA_API_KEY>", anon_content)

    def test_developer_mcp_script_download(self):
        resp = self.client.get("/developer/mcp/server.py")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/x-python", resp["Content-Type"])
        self.assertIn("TekloraClient", resp.content.decode("utf-8"))

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
