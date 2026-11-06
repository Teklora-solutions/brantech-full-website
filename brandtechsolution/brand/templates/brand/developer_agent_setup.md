# 🤖 Teklora Solutions — Developer & Autonomous Agent Setup Manifest

> **Notice to AI Agent (Claude Code, Cursor, Google Antigravity, Windsurf, Cline):**  
> You have received the official Teklora developer onboarding manifest from `{{ base_url|safe }}/developer/setup/`.  
> Follow the 4 instructions below to automatically set up the Teklora Developer Skill, configure the MCP server, establish the update mechanism, and guide the human developer.

---

## 🛠️ Step 1: Install the Teklora Developer Skill

You must install the canonical **`teklora-developer`** skill into your agent environment. This skill provides the required engineering rules, Conventional Commits referencing `[Task #N]`, branch naming standards (`<type>/<task-id>-<slug>`), the "Every Update" file maintenance contract, and the platform task ladder.

### How to fetch and save the skill:
Download `SKILL.md` directly from `{{ skill_url|safe }}` and write it to your skills folder:

```bash
# For Google Antigravity CLI:
mkdir -p ~/.gemini/antigravity-cli/skills/teklora-developer
curl -fsSL "{{ skill_url|safe }}" -o ~/.gemini/antigravity-cli/skills/teklora-developer/SKILL.md

# For Claude Code:
mkdir -p ~/.claude/skills/teklora-developer
curl -fsSL "{{ skill_url|safe }}" -o ~/.claude/skills/teklora-developer/SKILL.md

# For Project-level / Cursor skills:
mkdir -p .cursor/skills/teklora-developer
curl -fsSL "{{ skill_url|safe }}" -o .cursor/skills/teklora-developer/SKILL.md
```

---

## ⚡ Step 2: Install and Configure the Teklora MCP Server

Download the zero-dependency Python MCP server script:

```bash
mkdir -p ~/.teklora
curl -fsSL "{{ mcp_script_url|safe }}" -o ~/.teklora/teklora_mcp.py
chmod +x ~/.teklora/teklora_mcp.py
```

### Register the MCP Server

#### For Claude Code (CLI):
```bash
claude mcp add teklora python ~/.teklora/teklora_mcp.py --env TEKLORA_API_KEY="$TEKLORA_API_KEY" TEKLORA_BASE_URL="{{ base_url|safe }}"
```

#### For Cursor / Windsurf:
Add to `~/.cursor/mcp.json` or `.codeium/windsurf/mcp_config.json`:
```json
{
  "mcpServers": {
    "teklora": {
      "command": "python",
      "args": ["~/.teklora/teklora_mcp.py"],
      "env": {
        "TEKLORA_API_KEY": "${TEKLORA_API_KEY}",
        "TEKLORA_BASE_URL": "{{ base_url|safe }}"
      }
    }
  }
}
```

#### Available MCP Tools:
- `teklora_get_developer_profile`: Get profile, roles, and coding stack.
- `teklora_list_my_tasks`: List assigned tasks filtered by status (`open`, `in_review`, `done`).
- `teklora_get_task_details`: View task description, commits, and assignees.
- `teklora_complete_task_assignment`: Mark task assignment complete (transitions task ladder to In Review).
- `teklora_create_task`: Create a new task.
- `teklora_list_repositories`: View connected repositories.
- `teklora_search_knowledge_base`: Search documentation and memory documents.

---

## 🔄 Step 3: How to Receive Updates

To ensure your skill and MCP tools stay synchronized with Teklora platform updates:

1. **One-Line Update Script**:
   Whenever Teklora deploys new tools or updates developer guidelines, execute:
   ```bash
   curl -fsSL "{{ mcp_script_url|safe }}" -o ~/.teklora/teklora_mcp.py
   curl -fsSL "{{ skill_url|safe }}" -o ~/.gemini/antigravity-cli/skills/teklora-developer/SKILL.md
   ```
2. **Within the Repository**:
   If working within the `brantech-full-website` codebase, a standard `git pull` automatically updates the canonical files in `brandtechsolution/scripts/teklora_mcp.py` and `skills/teklora-developer/SKILL.md`.

---

## 💬 Step 4: AGENT INSTRUCTION — Guide the User on Their API Key

> 🚨 **AGENT ACTION REQUIRED:**  
> Now prompt and guide the human developer with the following instructions:

1. **How to get their API Key**:
   - Ask the user if they already have their Teklora Developer API Key (`tkl_live_...`).
   - If they do **not** have an API key, tell them to request one from the Teklora Platform Administrator or Lead Engineer (`admin@teklora.co.ke` or via the internal admin team).
   - If they are an administrator, they can generate and assign developer keys in Django Admin at:  
     `{{ base_url|safe }}/admin/staff/developerapikey/`.

2. **Where to put the API Key**:
   Instruct the user to set the key in their environment or MCP configuration:
   - **In shell environment** (recommended):
     ```bash
     # Add to ~/.bashrc or ~/.zshrc:
     export TEKLORA_API_KEY="tkl_live_your_secret_key_here"
     ```
   - **Or in their project `.env`**:
     ```bash
     TEKLORA_API_KEY=tkl_live_your_secret_key_here
     ```
   - **Or directly inside their MCP JSON config** (`~/.cursor/mcp.json`):
     Set the `"TEKLORA_API_KEY": "tkl_live_your_secret_key_here"` value in the `env` block.

3. **Verify Setup**:
   Once the user provides and saves the key, verify the setup with:
   ```bash
   python ~/.teklora/teklora_mcp.py --test --api-key "$TEKLORA_API_KEY" --base-url "{{ base_url|safe }}"
   ```
