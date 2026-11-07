---
name: teklora-developer
description: Official Teklora Solutions developer skill. Provides guidelines, architecture standards, task ladder workflow, Conventional Commits, and MCP tool instructions for engineering tasks.
---

# 🏛️ Teklora Developer Skill & Engineering Standards

This skill guides developers and autonomous AI agents working on the Teklora Solutions enterprise codebase and platform ecosystems.

---

## 📋 The "Every Update" File Maintenance Contract

Any modification to the codebase **must** maintain repository documentation integrity by fulfilling this contract before declaring work complete:

1. **`CHANGELOG.md`**:
   - Add an entry under `## [Unreleased]`.
   - Categorize under `### Added` (new features/endpoints), `### Changed` (modifications/refactors), or `### Fixed` (bug fixes).
2. **`docs/ROADMAP.md`**:
   - Check off completed milestone checklist items (`[x]`).
   - Add new milestone tasks when new capabilities or tracks are initiated.
3. **`README.md`**:
   - Update whenever architecture components, user-facing features, or environment variable setups change.
4. **`docs/specs/` & `docs/plans/`**:
   - Create or update specifications (`docs/specs/YYYY-MM-DD-<slug>-spec.md`) and execution plans (`docs/plans/YYYY-MM-DD-<slug>-plan.md`) for all non-trivial features or architecture refactors.

---

## 🌿 Branch & Git Commit Standards

- **Branch Naming**: `<type>/<task-id>-<slug>`
  - Features: `feat/task-41-developer-skill-mcp`
  - Bug fixes: `fix/task-19-whatsapp-validation`
  - Refactoring: `refactor/task-12-agent-harness`
  - Documentation: `docs/task-33-library-specs`
- **Conventional Commits**:
  - Always reference the numeric task ID:
    ```
    feat(staff): [Task #41] add developer api keys and mcp server
    fix(tasks): [Task #19] resolve assignment review state transition
    docs(knowledge-base): [Task #33] publish library specification
    ```

---

## 👥 Platform Task Lifecycle & Ladder

Tasks are managed natively in Teklora Admin (`brandtechsolution/tasks/`):

1. **Ladder Status**: `Open` $\rightarrow$ `In Review` $\rightarrow$ `Done`.
2. Developers mark their individual assignment complete via `teklora_complete_task_assignment` or `POST /api/work/tasks/<id>/complete/`.
3. Once all assignees mark complete, the task **automatically transitions** to `In Review`.
4. Only administrators holding the `manage_tasks` capability approve tasks to `Done`.

---

## 🛠️ Teklora MCP Tools Reference

When the Teklora Developer MCP server is configured in your agent environment, use these tools to inspect and advance work:

| Tool | Purpose | Key Arguments |
|---|---|---|
| `teklora_get_developer_profile` | Check your profile, permissions, and coding stack | None |
| `teklora_list_my_tasks` | List assigned tasks filtered by status | `status` (`open`, `in_review`, `done`), `search` |
| `teklora_get_task_details` | Retrieve full description, assignees, commits, and logs | `task_id` (e.g. 41) |
| `teklora_complete_task_assignment` | Mark your work done, submitting to In Review | `task_id` |
| `teklora_create_task` | Create a new task in the backlog | `title`, `description`, `priority` |
| `teklora_list_repositories` | List connected GitHub repos and default branches | None |
| `teklora_search_knowledge_base` | Semantic/text search across docs and memories | `query` |

---

## 🧪 Testing & Verification Standards

- **Run Automated Tests**: Always execute automated tests for affected apps prior to completing work:
  ```bash
  python brandtechsolution/manage.py test <app_name>
  ```
- **Error Handling**: Never fail silently or swallow exceptions into empty dicts.
- **Privacy & Compliance**:
  - Comply with Kenya Data Protection Act (KDPA 2019) and GDPR.
  - Store phone numbers in E.164 format (e.g., `+254...`).
  - Sensitive tokens and API keys must only store hashes (`key_hash`), never raw secrets in database records.
