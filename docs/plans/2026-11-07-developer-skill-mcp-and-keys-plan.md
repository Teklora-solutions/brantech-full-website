# Developer Skill, MCP Server, and API Keys Execution Plan

> Execution Plan for Task #41: Developer Skill, MCP Server, and Agent Auto-Setup Link

## Phase Breakdown

### Phase 1: Data Model & Authentication Backend
1. Create `DeveloperApiKey` model in `staff/models.py`:
   - `user`, `name`, `prefix`, `key_hash`, `scopes`, `is_active`, `created_at`, `last_used_at`.
   - Helper methods: `generate_key(user, name)`, `verify_key(token)`.
2. Implement `DeveloperApiKeyAuthentication` in `staff/authentication.py`.
3. Configure `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']` in `brandtechsolution/settings.py` so API keys authenticate on DRF views.
4. Run migrations for `staff`.

### Phase 2: Agent Auto-Setup Endpoints & Manifests
1. Implement public/canonical developer setup endpoints in `brand/views.py`:
   - `/developer/setup/` & `/developer/setup.md`: Renders Markdown setup instructions containing the 4 required steps: (1) skill installation, (2) MCP configuration, (3) updates & sync, (4) guiding the user on how to obtain their API key and where to set it.
   - `/developer/skill/SKILL.md`: Endpoint serving the raw canonical skill document.
   - `/developer/mcp/server.py`: Download endpoint serving the standalone MCP script.
2. Note on API keys: Per user requirements, developer keys are issued and managed securely through the Django Admin (`/admin/staff/developerapikey/`) rather than self-service API generation endpoints, minimizing endpoint surface area.

### Phase 3: Zero-Dependency Teklora Developer MCP Server
1. Create `brandtechsolution/scripts/teklora_mcp.py`:
   - Implements stdio JSON-RPC 2.0 MCP protocol.
   - Reads `TEKLORA_API_KEY` and `TEKLORA_BASE_URL` from env or CLI flags `--api-key` and `--base-url`.
   - Exposes tools:
     - `teklora_get_developer_profile`
     - `teklora_list_my_tasks`
     - `teklora_get_task_details`
     - `teklora_complete_task_assignment`
     - `teklora_create_task`
     - `teklora_list_repositories`
     - `teklora_search_knowledge_base`
   - Handles network errors gracefully and formats responses cleanly.

### Phase 4: Teklora Developer Skill
1. Create `skills/teklora-developer/SKILL.md`:
   - YAML frontmatter with `name: teklora-developer`.
   - Comprehensive rules:
     - Git branch naming & Conventional Commits referencing `Task #N`.
     - File maintenance contract (`CHANGELOG.md`, `ROADMAP.md`, `README.md`, `specs/plans`).
     - Native Task Ladder lifecycle.
     - MCP tool usage guide and examples.
     - Django / KDPA standards.
2. Also copy/register it in `.gemini/antigravity-cli/skills/teklora-developer/SKILL.md` so the current agent environment can load and test it immediately.

### Phase 5: Teklora Admin UI Section
1. Add navigation link in `brand/templates/brand/admin_base.html`:
   - Section link `Developer & Agents` (`/admin-panel/?section=developer`) with code/terminal icon.
2. Create section template `brand/templates/brand/admin/_developer.html`:
   - **Hero Agent Auto-Setup Card**:
     - Quick Copy Link input field.
     - 1-Click "Copy Prompt for Your Agent" button.
     - Quick instruction snippets for Claude Code, Cursor/Windsurf, Antigravity CLI.
   - **API Keys Management**:
     - "Generate New Key" modal with name input.
     - Secret key display modal with warning & copy button.
     - Table listing key name, prefix, creation date, last used date, status badge, and revoke button.
3. Add client-side logic in `brand/static/brand/js/admin/developer.js`.
4. Include template and script in `admin_panel.html` and `admin_base.html`.

### Phase 6: Automated Testing & Verification
1. Automated unit & integration tests in `staff/tests/test_developer_keys.py`:
   - Key generation, prefix, and hashing.
   - Authentication via Bearer token and X-Teklora-Api-Key.
   - Key revocation and rejection.
   - `/developer/setup/` endpoint rendering markdown and HTML.
   - `/developer/mcp/server.py` serving the script.
2. MCP server test:
   - Run stdio JSON-RPC handshake, list tools, and invoke a tool.
3. Update `CHANGELOG.md`, `ROADMAP.md`, and `README.md`.
