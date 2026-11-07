# Teklora library and EduShare delivery / task allocation

Status: user-approved first-wave assignment execution; later-wave packets remain proposals. Issued task IDs are recorded in the first-wave register after creation.
Date: 2026-11-04. No deadlines or workload capacity have been agreed.
Specification: [Document library](../specs/2026-11-04-document-library-spec.md).

## Scope and people

Two repositories, three workstreams: Teklora document library; EduShare student dashboard; EduShare admin dashboard. The user approved the library policies and first-wave assignment to active staff, holding Emmanuel. EduShare scope is confirmed as audit plus targeted fixes, not a redesign or new billing/financial/AI behaviour. School-local specification: `docs/specs/2026-11-04-dashboard-audit-and-targeted-fixes-spec.md`.

| Person | Account / allocation |
| --- | --- |
| David Njihia (requesting user) | `davidnjihia`, GitHub `BigAddict`: security/architecture gates and targeted reviews, not default implementer of every stream. |
| Junior Kariuki | `juniorkariuki`: Teklora library backend first; EduShare admin lead afterwards. GitHub mapping between `juniorkariuki735-code` and `jameskariuki8` needs confirmation. |
| Leon Musungu | `leonmusungu`, GitHub `luileonzawadi`: EduShare student lead first; Teklora UI integration reviewer afterwards. Do not assign a second person's workload to `teklora`: possible duplicate profile. |
| jmunuve | Onboarded full-stack profile, HTML/CSS/JS/TS and Node/Express/MongoDB: bounded template/JavaScript library work with Flask/Django orientation. Name not assumed to be Emmanuel. |
| Emmanuel | Verified active/onboarded `emmanuellamira`, GitHub `VPOUR`; Fullstack Engineer with React/Next/TS/Tailwind/Node/Express/MongoDB plus recorded mobile/desktop/tooling skills. Task #40 now assigned. Brantech permission is read (fork/PR or separately granted write); School permission is none. |
| Mugisha Lionel | `mugishalionel`: operational requirements, realistic sanitised meeting examples, workflow/privacy acceptance. Not automatically granted publication approval. |

Preserve each repository's server-rendered architecture; React/Next experience transfers, but neither project needs a new SPA for these tasks. New developers should get a pairing session and small reviewed PR before larger ownership.

## Evidence informing scope

Teklora paths and security gaps are in the specification. Existing task machinery is `tasks/models.py`, `api.py`, `serializers.py`: repository-linked tasks, per-person `TaskAssignment`, and `Open -> In Review -> Done` with `manage_tasks` approval.

EduShare inspected through authenticated GitHub default branch `main`, revision beginning `e1d528b`:
- `app/features/student_dashboard/{routes,services,repository}.py` already separates data loading and presents purchases, free downloads, purchase history, notifications, subscription, points/coins, streaks, badges, and a derived knowledge score. Do not silently change scoring or entitlement rules.
- `app/features/admin_moderation`, `admin_users`, `admin_payouts`, `admin_navigation`, and `finance` already exist. Keep feature boundaries instead of rebuilding a monolithic admin module.
- `docs/architecture.md` defines routes -> services -> repository -> shared SQLAlchemy Core metadata, Alembic migrations, shared tokens, Jinja components, and the admin layout.
- `app/features/admin_payouts/routes.py` calls `jsonify` in the AJAX withdrawal branch but does not import it in the inspected file. Static finding only: reproduce in isolated tests before treating it as a verified runtime incident. Financial action retries must not duplicate payouts.

## A. Teklora library task packets

Each LIB/EDU ID below is a planning key, not a database Task ID. First-wave tasks #32–#38 and #40 are issued in the [task register](2026-11-04-first-wave-task-register.md); later rows remain proposals. Reviewers need not be assignees.

| Key / priority | Deliverable | Proposed owner | Dependencies / reviewer |
| --- | --- | --- | --- |
| LIB-01 / High | Lock ACL and administrator definition, approved embedding-provider data handling, formats/limits/retention, API/view contract and threat model. Mugisha supplies researcher/meeting examples. | David | First; product acceptance with Mugisha. |
| LIB-02 / High | Document/version/grant/approval/chunk models, indexed constraints, safe migration and private-storage service. Server policy shared by listing/download/preview/share. | Junior | LIB-01; David reviews. |
| LIB-03 / High | Celery extraction, chunking, idempotent indexing/retry, provenance, deletion/replacement race protection; integrate existing model harness. | Junior | LIB-02; David reviews vector integration. |
| LIB-04 / High | ACL-aware internal/public retrieval adapter and tools; exclude protected library records from generic recall; revocation/cache/session isolation tests. | David | LIB-01 contract then LIB-02/03 integration; Junior reviews. |
| LIB-05 / Normal | Library list/detail/search UI, upload progress/error handling, preview/download controls and processing badges. Own only agreed library-list/detail templates and feature JS. | jmunuve | LIB-01 contract; LIB-02 endpoints; Leon reviews. |
| LIB-06 / Normal | Isolated sharing editor and admin approval queue/components; independent processing/public-review badges, reject/revoke states. Server remains authority. | Emmanuel | Released as task #40 after verified onboarding; LIB-01 contract, LIB-02 endpoints; coordinate with jmunuve #35; Junior reviews backend wiring. |
| LIB-07 / High | End-to-end security and operational acceptance; deploy behind flag, verify disabled rollback, publish staff guide. | David | LIB-02 through LIB-06; Mugisha conducts operational acceptance. |

Acceptance by task:
- **LIB-01:** implement and test a written policy matrix covering actor, action, audience and version/deletion states. Confirmed policies: active superusers or canonical Administrator-role staff with approval permission; per-document sharing; all uploads require administrator external-processing clearance separate from public approval; 25 MB per document/scan; include document OCR and Google Meet notes uploaded as DOCX; exclude recording ingestion and audio/video transcription; retain originals until deleted and purge live derivatives within 30 days. Validate provider/capacity/backup assumptions before enabling processing.
- **LIB-02:** unrelated/anonymous users cannot infer private titles or download by ID; group/org sharing works; non-admin users cannot approve or elevate themselves. Migration tested on disposable PostgreSQL.
- **LIB-03:** administrator-cleared documents/scans become ready with page/section citations through extraction/OCR and embedding; uncleared uploads make zero external calls. Unsupported/malformed/over-limit files fail clearly; retries are bounded and idempotent; stale jobs cannot expose old versions or resurrect deleted records.
- **LIB-04:** authorised results only before ranking/model invocation, including lexical fallback; public AI cannot see unapproved/revoked/replaced text; unscoped generic recall cannot leak library chunks; no cross-user cached conversation/citation leak.
- **LIB-05:** desktop/mobile/keyboard paths work for empty, populated, awaiting-clearance, queued, processing, ready, failed, blocked and forbidden states; failed upload does not appear successful; only permitted metadata is shown. Display document upload-authority acknowledgement and the 25 MB document/scan limit.
- **LIB-06:** owner/admin share controls differ from read/edit rights; separate external-processing clearance and public-approval controls are admin-only and enforced server-side; stale review requests cannot approve a replacement version.
- **LIB-07:** complete spec verification matrix, redacted operational examples, provider-data approval, retention procedures, and administrator release sign-off. No real confidential meeting documents in test fixtures.

## B. EduShare student dashboard

Lead: Leon. Scope below is a baseline proposal to refine, not an instruction to redesign unspecified functionality.

| Key / priority | Deliverable | Proposed owner | Dependencies / reviewer |
| --- | --- | --- | --- |
| EDU-STU-01 / High | Audit existing dashboard and student journeys; inventory bugs, route/data contracts, mobile screenshots and permission boundaries; agree a prioritised scope and add School-local spec/plan. | Leon | David approves scope; Mugisha tests user journeys. |
| EDU-STU-02 / Normal | Implement approved navigation/layout/accessibility and empty/loading/error states using existing Jinja/CSS tokens; preserve materials, subscriptions, badges and study metrics. | Leon | EDU-STU-01; David reviews data/security changes. |
| EDU-STU-03 / Normal | Bounded student notifications/material filtering interaction, selected from EDU-STU-01; maintain keyboard support, retry/error feedback and server authorisation. | jmunuve | EDU-STU-01/02 contract; after LIB-05 unless capacity explicitly changed; Leon reviews. |
| EDU-STU-04 / High | Regression and acceptance: own purchased/free materials only, correct subscriptions/history, no cross-student data, phone/desktop layouts and Study Hub navigation. | Leon | EDU-STU-02/03; David security review, Mugisha acceptance. |

Do not change the current knowledge-score calculation or subscription entitlements without a separately approved product task. New student AI behaviour is outside this dashboard scope.

## C. EduShare admin dashboard

Lead: Junior. David reviews permissions and financial writes; Leon provides a bounded shared-layout review after student delivery.

| Key / priority | Deliverable | Proposed owner | Dependencies / reviewer |
| --- | --- | --- | --- |
| EDU-ADM-01 / High | Inventory admin pages, existing shared-shell migration, RBAC/action matrix, moderation/users/payments workflows and agreed dashboard gaps; add School-local spec/plan. | Junior | After LIB-02/03 backend delivery; David approves scope, Mugisha supplies workflow cases. |
| EDU-ADM-02 / High | Reproduce payout AJAX missing-`jsonify` import; add focused regression then minimal fix if confirmed. Ensure response errors/retries do not repeat a financial side effect. | Junior | Separate small fix; may precede broad dashboard work after triage; David reviews. |
| EDU-ADM-03 / Normal | Approved dashboard overview/navigation/table improvements using existing admin shell and contextual actions; preserve filters/pagination and non-JS form fallback. | Junior | EDU-ADM-01; Leon reviews UI boundaries. |
| EDU-ADM-04 / Normal | Bounded reusable approval/status/filter component chosen in EDU-ADM-01; operate within existing permissions, no financial calculations or grant logic. | Emmanuel | Confirm account/access; after LIB-06; Junior reviews. |
| EDU-ADM-05 / High | Regression of approve/reject, user verification/role changes, withdrawals and exports; owner vs limited-admin permission matrix, CSRF, double-click/idempotency and accurate failure feedback. | Junior | EDU-ADM-02/03/04; David security/financial sign-off, Mugisha acceptance. |

Financial logic, accounting rules and role grants are not visual polish. Any changes require explicit scope and tests, not a UI-only PR.

## Sequencing and capacity

1. Actual first wave: David #33 implements the ACL/retrieval contract/foundation, Mugisha #32 supplies classification cases, Leon #36 starts student audit, Mugisha #38 prepares EduShare UAT, Junior #34 starts library discovery and #37 bounded admin triage, and jmunuve #35 starts template/fixture preparation.
2. Junior implements LIB-02/03. jmunuve and Emmanuel build non-overlapping library UI slices against the agreed contract once access is confirmed. David implements LIB-04.
3. Leon completes the approved student baseline, then reviews library UI. Integrate and test library through LIB-07.
4. Junior leads admin discovery and delivery after library backend ownership is clear; reproduce a confirmed urgent payout defect sooner in its own PR. New developers move to EDU-STU-03 / EDU-ADM-04 after their library tasks, not simultaneously by default.
5. Do not invent delivery dates until scope, access, availability and review capacity are confirmed. Emmanuel's onboarding is now verified and LIB-06 is assigned as #40; School work remains gated on a separately granted repository access and capacity check.

## Task board and Git handoff

- The earlier planning pass created no live assignments. The user subsequently authorised first-wave production tasks for David, Junior, Leon, jmunuve and Mugisha; Emmanuel's held task was released as #40 after onboarding verification. No permission changes, deployments or GitHub issues are authorised by task creation.
- Create approved packets in Teklora Admin Tasks, linking the appropriate `Repository.full_name`: `Teklora-solutions/brantech-full-website` or `Teklora-solutions/school`.
- Active/onboarded identities are checked before creation. Availability/due dates remain unconfirmed; use actual numeric task IDs in branches (`feat/task-<id>-library-upload`) and Conventional Commits (`feat(knowledge-base): [Task #<id>] ...`). Planning keys are not substitutes for IDs.
- Contributors mark only their own `TaskAssignment` complete. All assignments complete moves the task to In Review; an authorised `manage_tasks` administrator approves Done. A reviewer mention alone must not block completion as an accidental assignee.
- Keep this cross-project plan in Teklora for coordination. EduShare owners must add its accepted scope/spec/plan plus README/CHANGELOG/ROADMAP updates in the School repository before implementation. Do not put EduShare feature checkboxes in Teklora's roadmap: its importer could create tasks under the wrong repository.

## Verification commands and evidence

Teklora library implementation: `cd brandtechsolution && python manage.py test knowledge_base ai_workflows staff tasks`, using a dedicated PostgreSQL/pgvector database and stub model providers. UI smoke checks include mobile/desktop/keyboard and independent approval/index states.

EduShare: use isolated `uv run pytest` targeted tests for dashboard/RBAC/financial changes, plus the documented foundation suite:

```sh
uv run pytest tests/test_application_foundation.py tests/test_admin_layout.py tests/test_platform_costs.py tests/test_file_storage.py tests/test_previews.py tests/ai/test_credential_verify_service.py -q
```

Set a dedicated `DATABASE_URL` before importing EduShare modules. Its architecture documentation warns factory overrides alone do not isolate the process-level database. Never execute migrations, payout actions or write-path tests against production. Each PR carries test output and relevant before/after screenshots; static findings are labelled until reproduced.
