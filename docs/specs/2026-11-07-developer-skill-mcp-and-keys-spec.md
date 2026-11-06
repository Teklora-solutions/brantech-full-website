# Developer Skill, MCP Server, and API Keys Specification

> Specification for Task #41: Developer Skill, MCP Server, and Agent Auto-Setup Link for Teklora Solutions engineers and autonomous AI agents.

## 1. Overview & Objectives

Teklora Solutions operates a hybrid engineering workforce combining human developers and autonomous AI coding agents (Claude Code, Cursor, Google Antigravity, Windsurf, Cline). To integrate developer workflows natively with the platform:

1. **Staff Developer API Keys**: Staff accounts can generate, manage, and revoke personal API keys (`tkl_live_...`) to authenticate their agents and CLI tools.
2. **One-Click Agent Setup Link**: In the admin panel, developers can copy an auto-setup URL or 1-click instruction prompt to paste into their favourite AI agent. The endpoint delivers tailored markdown instructions, machine-readable MCP configurations, and skill loading instructions.
3. **Teklora Developer Skill (`teklora-developer`)**: An agent skill defining canonical engineering rules:
   - Branch naming: `<type>/<task-id>-<slug>`
   - Conventional Commits: `<type>(<scope>): [Task #<id>] <description>`
   - The "Every Update" contract (`CHANGELOG.md`, `ROADMAP.md`, `README.md`, `docs/specs/`, `docs/plans/`)
   - Platform task lifecycle (Open → In Review → Done)
   - Privacy, Kenya Data Protection Act (KDPA 2019), and Django security standards
4. **Teklora Developer MCP Server**: A zero-dependency stdio Model Context Protocol server exposing tool capabilities directly to agents:
   - `teklora_get_developer_profile`
   - `teklora_list_my_tasks`
   - `teklora_get_task_details`
   - `teklora_complete_task_assignment`
   - `teklora_create_task`
   - `teklora_list_repositories`
   - `teklora_search_knowledge_base`

---

## 2. Security & Authentication Architecture

- Keys follow the format `tkl_live_<32_random_alphanumeric_bytes>`.
- Plaintext keys are shown **only once** upon generation. The database stores:
  - `prefix`: The first 12 characters (`tkl_live_xxxx...`) for identification.
  - `key_hash`: SHA-256 hash of the complete token for cryptographic validation.
- DRF Authentication class `DeveloperApiKeyAuthentication` accepts:
  - Header: `Authorization: Bearer tkl_live_...`
  - Header: `X-Teklora-Api-Key: tkl_live_...`
- Keys update `last_used_at` upon authenticated requests.
- Staff members can revoke keys at any time. Revoked or inactive keys immediately reject further requests with `401 Unauthorized`.

---

## 3. Web & API Endpoints

| Endpoint | Method | Permission | Description |
|---|---|---|---|
| `/admin-panel/?section=developer` | GET | Staff member | Developer & Agent UI section in Teklora Admin |
| `/api/staff/developer/keys/` | GET | Staff member | List developer's active & revoked API keys |
| `/api/staff/developer/keys/` | POST | Staff member | Generate a new key, returns plaintext secret once |
| `/api/staff/developer/keys/<id>/revoke/` | POST | Staff member | Revoke an existing API key |
| `/developer/setup/` | GET | Public / Key Query | Agent auto-setup instruction page & markdown instructions |
| `/developer/mcp/server.py` | GET | Public | Standalone zero-dependency Python MCP server script |

---

## 4. MCP Tools & Protocol

The MCP server implements JSON-RPC 2.0 stdio protocol matching the Anthropic Model Context Protocol specification:
- `initialize` & `notifications/initialized`
- `tools/list`
- `tools/call`
- `ping`

Zero external dependencies outside Python standard library (`sys`, `json`, `urllib.request`, `os`, `argparse`).
