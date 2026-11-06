# 🤖 Teklora Solutions — Developer & Autonomous Agent Setup

{% if is_valid_key %}
> **Welcome, {{ developer.get_full_name|default:developer.username }} (@{{ developer.username }})!**  
> Primary Role: **{{ profile.primary_role|default:"Fullstack Engineer" }}** | Scopes: **{{ profile.scopes|join:", "|default:"Engineering" }}**  
> Your authenticated session has generated personalized agent configuration instructions below.
{% else %}
> **Teklora Developer Setup Instructions**  
> To personalize this configuration with your authenticated developer identity, generate an API key at [Teklora Admin → Developer & Agents]({{ base_url }}/admin-panel/?section=developer) and reload with `?key=YOUR_API_KEY`.
{% endif %}

---

## ⚡ Agent Quick Setup Command

If you are an autonomous coding agent (Claude Code, Cursor, Google Antigravity, Windsurf, Cline), execute the following steps to configure your environment:

### Step 1: Download & Install Teklora MCP Server

Run this command in your terminal:
```bash
mkdir -p ~/.teklora
curl -fsSL "{{ mcp_script_url }}" -o ~/.teklora/teklora_mcp.py
chmod +x ~/.teklora/teklora_mcp.py
```

### Step 2: Register MCP Server With Your Tool

#### For Claude Code (CLI)
Execute:
```bash
claude mcp add teklora python ~/.teklora/teklora_mcp.py --env TEKLORA_API_KEY="{{ key|safe }}" TEKLORA_BASE_URL="{{ base_url|safe }}"
```

#### For Cursor / Windsurf
Add this to your `~/.cursor/mcp.json` (or project `.cursor/mcp.json`):
```json
{
  "mcpServers": {
    "teklora": {
      "command": "python",
      "args": ["~/.teklora/teklora_mcp.py"],
      "env": {
        "TEKLORA_API_KEY": "{{ key|safe }}",
        "TEKLORA_BASE_URL": "{{ base_url|safe }}"
      }
    }
  }
}
```

#### For Google Antigravity / Claude Desktop
Add to your MCP configuration:
```json
{
  "mcpServers": {
    "teklora": {
      "command": "python",
      "args": ["~/.teklora/teklora_mcp.py"],
      "env": {
        "TEKLORA_API_KEY": "{{ key|safe }}",
        "TEKLORA_BASE_URL": "{{ base_url|safe }}"
      }
    }
  }
}
```

---

## 📚 Step 3: Install the Teklora Developer Skill

Write the following specification to your agent skills directory (e.g. `~/.gemini/antigravity-cli/skills/teklora-developer/SKILL.md` or `.claude/skills/teklora-developer/SKILL.md`):

```markdown
---
name: teklora-developer
description: Official Teklora Solutions developer skill. Provides guidelines, architecture standards, task ladder workflow, Conventional Commits, and MCP tool instructions for engineering tasks.
---

# 🏛️ Teklora Developer Skill & Engineering Standards

### 📋 The "Every Update" File Maintenance Contract
1. CHANGELOG.md: Add an entry under ## [Unreleased] (### Added, ### Changed, ### Fixed).
2. docs/ROADMAP.md: Check off completed items or add new milestone tasks.
3. README.md: Update when user-facing features or architecture change.
4. docs/specs/ & docs/plans/: Create or update specs and plans before implementing.

### 🌿 Branch & Git Commit Standards
- Branch Naming: `<type>/<task-id>-<slug>` (e.g., `feat/task-41-developer-skill-mcp`)
- Commit Messages: Conventional Commits with task ID: `<type>(<scope>): [Task #<id>] <description>`

### 👥 Task Status Ladder
Open -> In Review -> Done
- Complete your assignment via `teklora_complete_task_assignment`.
- Once all assignees mark complete, the task transitions automatically to In Review.
- Only administrators approve tasks to Done.
```

---

## 🧪 Step 4: Verify Connection

Test your MCP server connection by invoking the profile tool:
```bash
python ~/.teklora/teklora_mcp.py --test --api-key "{{ key|safe }}" --base-url "{{ base_url|safe }}"
```
Or use the MCP tool: `teklora_get_developer_profile`.
