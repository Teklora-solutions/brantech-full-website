# Task Deliverables Backed by the Knowledge Library — Implementation Plan

**Status:** Implemented and verified locally; controlled release pending. User authorized implementation after the source audit; no live task mutations or deployment authorized. API/data contract: `docs/specs/2026-11-12-task-document-deliverables-spec.md`. The original detailed checklist below remains the full design/release checklist; the implementation record at the end distinguishes verified delivery from deferred follow-ups.

**Scope:** Let staff submit documents as task-assignment deliverables alongside the existing code workflow. Originally planning-only; implementation now has a separate API/security specification as required by repository engineering policy.

**Task allocation:** Not assigned. Do not invent task IDs, create live assignments, or change task-board statuses as part of writing this plan.

## 1. Outcome and boundaries

A non-technical assignee should be able to open their task, upload a report or choose an existing library document, add a note, and submit their work for administrator review without GitHub, an API key, or a developer profile. A developer can use the same flow for research or design documents; eligibility depends on the task, not a person's role label.

- Tasks own submission, feedback, acceptance and completion.
- The Knowledge Library owns original files, versions, document permissions, processing clearance, publication approval and deletion.
- Reuse the existing admin task workspace and library UI/theme. Do not introduce a separate frontend or duplicate file storage.
- Keep `Open → In Review → Done`. Completing an assignment is not administrator approval of the task.
- **Work acceptance, external-processing clearance and public-use approval are three independent decisions.** A document can be reviewed as an authenticated original file while processing is pending or blocked. No AI processing is necessary to submit or accept work.
- Keep the library always available; do not add a feature flag.
- No public deliverable portal, new file formats, external submission links, collaborative editor or AI grading in the first release.

## 2. Existing integration points to preserve

- `tasks/models.py`: `TaskAssignment.completed_at` drives `Task.refresh_review_state()`; submissions must remain assignment-specific.
- `tasks/api.py`: completion already locks the task; `approve` requires `manage_tasks`. Existing `reopen` resets every assignment. Introduce targeted revision requests without silently changing this existing whole-task action.
- `tasks/github.py`: GitHub closing commits, merged branches and roadmap/documentation automation can finish assignments. These paths must not bypass a new document requirement or complete unrelated assignees on mixed-delivery tasks.
- `tasks/serializers.py`, `brand/templates/brand/admin/_tasks.html` and `brand/static/brand/js/admin/tasks.js`: task creation, detail, completion and review surfaces.
- `knowledge_base/library/services.py`: reuse `upload_document` and library validation/private storage; uploads begin without processing clearance or publication approval.
- `knowledge_base/views.py`: the current download route serves the **current** version. A submitted deliverable needs a separate authorized, exact-version download path.
- `knowledge_base/library/policy.py` and `knowledge_base/tasks.py`: extend access deliberately and preserve immediate deletion denial plus the existing live-file/vector purge lifecycle.

## 3. Delivery sequence

### Phase 1 — Submission records and compatibility

- [ ] Add task delivery requirements: **Document**, **Code**, or **Either**. Preserve existing tasks under an explicit legacy/standard-completion default; do not retroactively require files or commits or reopen approved work. Administrators choose stricter requirements for new tasks.
- [ ] Model an assignment submission round with submitter, timestamp, note, revision number and review state (`Submitted`, `Accepted`, `Changes requested`, plus superseded history). Support multiple document attachments in one submission.
- [ ] Each attachment references an exact `LibraryVersion`, not merely a document/current-version pointer. Keep the parent document relationship available for authorization and deletion checks. Do not copy originals.
- [ ] Use append-only submission rounds and review events: a new revision supersedes an earlier round but never rewrites its files, note or prior feedback. Record reviewer identity, decision, rationale and timestamp.
- [ ] Separate the live assignment link from retained task/submission identity: current assignment replacement deletes `TaskAssignment` rows, so use nullable historical links and stable attribution rather than cascading away submission history on unassignment. A new assignee must not inherit another person's accepted work automatically.
- [ ] Add explicit related names, filtered-field indexes, unique revision constraints and timezone-aware timestamps. Avoid duplicated status sources: compute the current submission from one authoritative relation/service.
- [ ] Define deletion behavior in migrations: document/version purge must be able to null historical references without deleting the submission/review event or blocking privacy deletion. Show an unavailable-evidence marker, not a reconstructed file. Retain only minimal audit metadata under the applicable retention policy.

**Exit:** Migrations apply/rollback/reapply on an isolated database; historical tasks and commit records behave as before.

### Phase 2 — Version-scoped access and submission services

- [ ] Add services to upload/select evidence, submit a round, request revisions and accept a round. Enforce active staff, current assignment membership, task state and object-level permissions on every mutation; never trust client-supplied submitter/reviewer fields.
- [ ] Reuse library upload validation and authority acknowledgement. Selecting an existing document requires **share authority**, not just read/edit access, because submission grants reviewers access. Restrict selection to its current version at submission time; subsequent review/download remains pinned to that version.
- [ ] Create an explicit task-submission access relationship scoped to the submitted version. Require affirmative sharing confirmation identifying the audience: the submitter and active staff holding `manage_tasks` for review. Do not create organisation visibility, broad library grants or access to other versions. Existing independent library permissions remain independent.
- [ ] Provide authenticated, audited attachment-only download of the pinned original. Recheck actor status, submission audience, document deletion and version ownership on every request. Do not redirect reviewers to the current-version download URL or expose private storage paths.
- [ ] Keep submission-only access out of ordinary library search, semantic recall, public tools and generic `Memory.recall`. Reviewing a submitted original must not permit provider calls or retrieval of other private document contents.
- [ ] A reviewer losing `manage_tasks`, an account becoming inactive, or a document being deleted immediately loses the corresponding submission access. Unassigned staff lose assignment-derived access; the uploader's independent ownership is unaffected. Reassignment does not expose previous private evidence to the replacement assignee.
- [ ] Lock the task and relevant assignment/submission/document rows in a consistent order. Recheck the expected version and submission revision inside the transaction; reject stale requests instead of silently swapping evidence. Use idempotency/unique constraints to prevent duplicate submissions and duplicate review notifications.
- [ ] Treat upload and submission as separate steps: a successfully uploaded private document may remain in the library if final submission fails, with a clear retry message. Do not silently delete user-owned work. Ensure failed uploads/rolled-back file writes follow existing orphan cleanup.

**Exit:** Submitted version N remains downloadable through its authorized submission even after N+1 becomes current; no broader document or AI access is conferred.

### Phase 3 — Task completion and review integration

- [ ] Centralize delivery validation in a shared completion service used by API completion, GitHub/roadmap/documentation automation and the existing MCP completion endpoint. Inspect all call sites that set `completed_at` or refresh review state.
- [ ] **Document:** require a submitted current round with at least one available authorized attachment. **Code:** require qualifying linked commit evidence. **Either:** require one qualifying path. Legacy tasks keep their existing completion behavior.
- [ ] For new Code/Either tasks, define qualifying code evidence as a linked default-branch commit attributable to the assignee, or an explicit, audited manager association for shared team work. A task-wide commit cannot automatically satisfy every person's assignment. Preserve legacy GitHub automation for legacy tasks; do not build a second code-review system.
- [ ] Upload/selection alone does not complete work. An explicit **Submit work** action freezes the round and marks the assignee complete atomically; the task enters `In Review` only after every current assignee is complete. Keep existing developer completion usable when its selected delivery requirement is satisfied.
- [ ] A `manage_tasks` reviewer accepts a submission or requests changes with mandatory feedback. A targeted changes request resets only that assignment, reopens the task as necessary and leaves other assignees' evidence/decisions intact. Keep existing whole-task `reopen` semantics available and audited.
- [ ] Resubmission creates a new round and requires a fresh decision. Editing/replacing library content cannot update a submitted round. Ordinary document replacement does not invalidate an accepted pinned version; deletion/revocation of submission evidence must block pending approval until resolved.
- [ ] Task approval remains an explicit manager action, not a side effect of accepting one submission. Require all current assignees to be complete and all current document submissions to be accepted and accessible before `Done`. Prevent new submissions or mutations on a Done task until an administrator reopens it.
- [ ] Preserve acceptance history when an approved task is reopened; record which current rounds need fresh review. Do not reuse a previous acceptance automatically after a new submission.
- [ ] Add privacy-safe task/library audit entries and after-commit notifications for submission, acceptance, revision requests and review readiness. Avoid notification duplication and private filenames, excerpts or storage keys in board-wide activity, email or logs.

**Exit:** Multi-assignee and mixed-delivery tasks cannot bypass review, and every completion path honors the same evidence requirements.

### Phase 4 — Staff and reviewer UI

- [ ] Add a **Deliverables** section inside task detail, grouped by assignee, showing the requirement, current submission, version, submitted time, review state and feedback. Keep commits alongside documents rather than splitting the workspace by staff type.
- [ ] Provide **Upload document**, **Choose from library**, submission notes and an explicit sharing/audience confirmation. Reuse library styling and file validation/progress/error patterns, including keyboard-accessible native controls.
- [ ] The picker lists only eligible shareable documents, supports search/pagination, and clearly identifies the version being selected. An opaque ID lookup must enforce the same eligibility as the picker.
- [ ] Provide **Submit work** and **Submit revision** with a clear completion summary. Show upload, submitting, validation, stale-version, access-revoked, network-failure and success states honestly; prevent double submission and preserve user input on recoverable failures.
- [ ] Reviewers can download the exact submitted files, read notes/history, accept, request changes and finally approve the task. Pending/blocked extraction must not disable original-file review.
- [ ] Hide private evidence metadata, attachment counts and feedback from unrelated board readers, including API serializers and board-wide activity. Show the task's ordinary public-to-staff metadata without implying that board visibility grants document access.
- [ ] Add permission-checked task backlinks on library detail where useful; do not reveal private task/submission relationships to unrelated document viewers.
- [ ] Verify desktop/mobile, light/dark, focus order, labelled controls, screen-reader status announcements and empty/error/populated states in a real browser before calling the UI complete.

**Exit:** A staff member without GitHub or developer capabilities can submit a document and complete a full feedback/resubmission cycle from Tasks.

### Phase 5 — Regression coverage and release

- [ ] Model/service tests: immutable version pinning, multi-file rounds, stale requests, duplicate retries, upload/submission failure recovery, assignment removal/re-addition, account removal, deleted evidence and retained minimal audit history.
- [ ] ACL tests: self versus other assignee, unrelated board reader, read-only/edit-only library user versus sharer, manager without library-publication authority, deactivated user, manager capability revocation, guessed IDs, mismatched document/version and private serializer/activity leakage.
- [ ] Lifecycle tests: multiple assignees finishing concurrently, targeted changes versus whole-task reopen, superseded submissions, accepted round followed by revision, Done-task restrictions and approval after evidence becomes unavailable.
- [ ] Compatibility tests: existing tasks/commits, code/either attribution, GitHub polling/webhooks, roadmap/documentation automation, API-key/MCP completion and duplicate notification suppression. Ensure none bypasses Document requirements.
- [ ] Library regression tests: no automatic processing/public approval or provider calls, no stale/public semantic retrieval, replacement preserves pinned originals, immediate deletion denial and successful normal purge without retained files/vectors or blocked foreign keys.
- [ ] Run `python manage.py test tasks knowledge_base staff ai_workflows` from `brandtechsolution/`; include relevant `brand` panel tests. Use isolated PostgreSQL/pgvector and fake providers; record any baseline failures separately rather than claiming a fully green suite.
- [ ] Browser acceptance: non-developer upload → submit → manager requests changes → revised upload → accept → approve, existing-library selection, mixed multi-assignee delivery, deleted/inaccessible evidence, and mobile/desktop in both themes. Also verify the legacy developer path.
- [ ] Update README usage guidance, changelog and roadmap when implementation ships. Check migrations, Django system checks, JS syntax and whitespace. Record evidence and limitations in this plan.
- [ ] Deploy migrations/application together, smoke-test with dedicated test accounts and monitor safe error/audit signals. Do not auto-convert existing tasks, create live assignments or approve production work. If rolling back, retain submission data; do not drop tables containing real evidence/history.

## 4. Recommended implementation order

1. Data model and privacy-safe version access, with tests.
2. Submission/review services and shared completion guards, including all automation paths.
3. Task API/serializers and the complete staff/reviewer UI.
4. Browser acceptance, compatibility regression, documentation and controlled release.

Each increment must leave the existing task board and library usable. No live task-board assignment/status mutation, merge, push or production deployment is authorized by this implementation request.

## 5. Implementation and verification record

### Delivered locally
- Task delivery requirements default to Standard without converting existing tasks. Added immutable assignment submission rounds, exact nullable LibraryVersion attachments and append-only review events. Assignment/account/evidence removal does not cascade away submission history.
- Separate private upload, paginated/searchable share-authorized library picker, explicit audience confirmation, multi-file submit (up to 10), idempotent retry UUIDs and stale-submission/current-version checks under task/document locks.
- Current submitter and active manage_tasks reviewers receive submission-only original-file access. Other assignees/board readers receive no private notes, filenames/counts, feedback or downloads. No broad library grants, public retrieval, provider calls or approval changes are introduced.
- Shared evidence guards cover API/API-key/MCP completion, task approval and the common GitHub/roadmap/documentation finishing service. New strict code requirements use attributed default-branch commits; legacy completion remains compatible. All current document rounds require acceptance before task approval.
- Targeted changes requests reset only the relevant assignment. Whole-task reopen and self-undo retain past reviews and require new submission rounds. Deleted/purged/missing evidence blocks review/approval; ordinary replacement preserves pinned evidence.
- Task modal includes upload/progress/error recovery, existing-library selection, notes, consent, immutable history, exact-version downloads, reviewer feedback/acceptance and task-level delivery requirement selection. Document-required tasks use explicit Submit work rather than a misleading bare completion button.

### Verification
- **964 tests pass** across tasks, knowledge_base, staff, ai_workflows and brand.test_admin_access, including 25 new submission tests (with PostgreSQL concurrent retry and multi-assignee completion coverage). Test-process-only MD5 password hashing accelerated the suite; application password configuration is unchanged. API-key tests verify the MCP endpoint's document guard.
- An initial broad run had two runner-environment failures (explicit tracing=false contradicted a default-setting test, and sys.argv was populated after loading TESTING). Corrected the runner setup and reran all affected tests successfully; no application workaround was added.
- Fresh isolated PostgreSQL database: migration apply → rollback to tasks.0005 → reapply passed. No production database or task records were changed.
- Chromium against an isolated database/private storage: upload → submit → exact original download → changes request → existing-library selection → revision → acceptance → separate task approval passed. Legacy completion passed. Validation and a simulated upload network failure preserved the submission note/file selection; retry succeeded. Native keyboard focus order, unique modal control IDs and no horizontal mobile overflow were checked; desktop/mobile dark/light screenshots captured and inspected; no page JavaScript errors. Fixture login needed a normal CSRF-cookie issuance step because force_login bypasses the login form.
- Browser artifacts: `/tmp/teklora-deliverable-upload-desktop-dark.png`, `/tmp/teklora-deliverable-review-mobile-dark.png`, `/tmp/teklora-deliverable-review-mobile-light.png`, `/tmp/teklora-deliverable-review-desktop-light.png`. Automated lifecycle/ACL tests cover additional mixed-assignee, deletion, account/permission revocation and stale-version cases; these are not claimed as separate manual production browser checks.

### Remaining release/follow-up work
- Production migration/application/static deployment and dedicated-account smoke testing require release authorization. Do not reverse/drop submission tables containing real evidence.
- Explicit manager association of shared-team code commits is deferred; strict code evidence currently requires direct assignee attribution. No implicit completion of the other assignees is allowed.
- Optional permission-checked backlinks from library detail are deferred; task reviewers already have exact-version links in Tasks.
- No new standalone evidence-sharing revocation switch is added; unassignment, role/account revocation and normal library deletion/purge enforce the current access lifecycle.
