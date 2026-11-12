# 🗺️ Teklora Platform Roadmap

This document serves as the high-level roadmap and strategic milestone tracker for Teklora Solutions Ltd. It aligns repository development with the platform's internal task pipeline (`/admin-panel/?section=tasks`).

---

## 🎯 Active & Upcoming Milestones

### 🚀 Milestone 1: Staff Onboarding & Capability Profile Matrix *(Completed)*
- [x] **Technical / Coding Capabilities Matrix**:
  - [x] Add coding capabilities schema (languages, frameworks, primary role, GitHub handle) to `StaffProfile`.
  - [x] Support primary programming languages, frameworks, and skill bio in profile API and admin view.
- [x] **WhatsApp Communication Setup**:
  - [x] Integrate WhatsApp number collection in onboarding flow with E.164 sanitization & validation (`phone.py`).
  - [x] Add quick-action WhatsApp button to Staff directory in Admin panel (`wa.me` integration).
- [x] **Interactive Onboarding UI**:
  - [x] Onboarding redirect (`/staff/onboarding/`) for staff accounts.
  - [x] Capability selection pill-selector and comprehensive profile completion form.

---

### 🧠 Milestone 2: Unified Agent Harness & Editorial Intelligence *(Completed)*
- [x] **Unified Model Harness**:
  - [x] Centralize model execution, routing, and provider abstraction into `ai_workflows/harness/` (`docs/specs/2026-09-21-unified-agent-harness-design.md`).
  - [x] Multi-provider configuration supporting Gemini, Anthropic, OpenAI, DeepSeek, OpenRouter, and Codex.
  - [x] Unified exponential backoff, rate-limit retry policies, and automated admin failure alerts (`alerts.py`).
  - [x] Newsroom agent migration across 6 core editorial/research agents removing isolated model clients and fallbacks.
  - [x] Consolidate the seven per-agent pipeline apps into domain packages inside `editorial/` (`docs/plans/2026-10-16-editorial-consolidation-plan.md`).
- [x] **Persistent Semantic Knowledge Base & Memory**:
  - [x] Single-corpus semantic memory with per-vector model provenance (`memory.py`).
  - [x] Scored re-embedding on model switch with vector indexing.
  - [x] Token usage accounting, pricing catalog (`pricing.toml`), and budget tracking (`usage.py`).

---

### 💻 Milestone 3: GitHub Manager & Developer Portal *(In Progress)*
- [ ] **GitHub Admin Panel Integration** (`/admin-panel/?section=githubSync`):
  - [x] Live repository management dashboard with search, filtering, and project conversion.
  - [x] Background sync, commit counts tracking, and interactive README markdown inspector (`brand/github_service.py`).
  - [x] Persistent database snapshots for GitHub metadata, account details, README/commits and document audits, with background refresh, revision/hash reuse and rate-limit backoff (`docs/specs/2026-10-28-github-database-cache-spec.md`).
  - [x] Repository document standard: README, CHANGELOG, ROADMAP and LICENSE checked per repository, with an alert and a Documents tab (`docs/specs/2026-10-20-repo-docs-standard-spec.md`).
  - [x] Automatically turn missing or invalid required documents into assignable documentation repair tasks in Project backlog, with deduplication and review on resolution (`docs/specs/2026-10-28-documentation-repair-backlog-spec.md`).
  - [x] Show whether the GitHub key is a personal account or an organisation.
  - [x] Import roadmap leaf items automatically from GitHub-synced projects into a separate unassigned backlog with project filters and manager-led assignment (`docs/specs/2026-10-28-roadmap-backlog-spec.md`).
  - [x] Link task commits and submit closing commits or merged task branches for review through polling and an optional signed webhook; show project import status and task commit details in Admin Tasks (`docs/specs/2026-10-28-github-task-automation-spec.md`).
  - [x] **Developer Skill, MCP Server & Agent Setup Link**:
    - [x] Staff Developer API Keys (`DeveloperApiKey` model, key generation, prefixing, revocation, and DRF authentication).
    - [x] Teklora Admin Developer & Agents workspace (`/admin-panel/?section=developer`) with 1-click agent setup link.
    - [x] Agent setup instruction endpoint (`/developer/setup/`) serving tailored markdown setup instructions for autonomous agents.
    - [x] Zero-dependency Teklora Developer MCP Server (`brandtechsolution/scripts/teklora_mcp.py`) exposing task management, profile, repos, and knowledge base search.
    - [x] Teklora Developer Skill (`skills/teklora-developer/SKILL.md`) codifying architecture standards, task ladder, git conventions, and file maintenance contract.
  - [ ] Staff GitHub repository discovery: scan and import accessible repositories from configured staff GitHub profiles.
  - [ ] Automated PR status linking with Teklora Admin Tasks.
- [ ] **Client Project Delivery Hub**:
  - [ ] Client-facing milestone tracking and deliverable inspection.

---

### 💼 Milestone 4: Careers Page & Admin Management System *(Initiated / In Progress)*
- [ ] **Job Openings Schema & Data Architecture** (`docs/specs/2026-10-11-careers-page-admin-management-spec.md`):
  - [ ] `JobOpening` model with department, work mode, employment type, qualifications, and active flags.
  - [ ] Django admin registration with search and status filters.
- [ ] **Teklora Admin Careers Management Hub** (`/admin-panel/?section=careers`):
  - [ ] Role listing with active/draft badges and instant publish/unpublish toggles.
  - [ ] Modal creation and editing with structured duties & requirements fields.
- [ ] **Dynamic Public Careers Experience** (`/careers/`):
  - [ ] Live database querying replacing hardcoded static positions in `brand/careers.html`.
  - [ ] Department filtering, expandable position details, and pre-filled email application trigger.
  - [x] Empty state fallback with general resume submission prompt.
- [x] **Closing roles, tracks and partners**: Close / Reopen for jobs and tracks, Hide / Show for partners, in the panel; closed roles leave `/careers/` and late applicants get an automatic applications-closed reply.

---

### 🤝 Milestone 5: Dedicated Partnerships & CSR Platform *(Completed)*
- [x] **Standalone Partnerships & CSR Hub** (`/partnerships/`):
  - [x] Dedicated route and template (`partnerships.html`) styled with glassmorphism and Tailwind tokens.
  - [x] 4-step collaborative framework outlining how organisations and people can partner with Teklora.
  - [x] Interactive modal application form with prefilled track metadata and WhatsApp direct liaison.
- [x] **Embedded CSR Ecosystem**:
  - [x] Dedicated Corporate Social Responsibility mandate: touching the lives of vulnerable children (orphanages, rescue shelters, digital literacy), and ministries spreading the Gospel of Jesus Christ (churches, evangelism, congregation tech).
  - [x] EduShare Zero-Rating Alliance: Public campaign inviting telcos (Safaricom, Airtel, MTN) and educational donors to partner with Teklora to sponsor student bandwidth and zero-rate syllabus access across Kenya and Africa.
- [x] **Admin-Managed Partnership Pipeline**:
  - [x] `PartnershipType` and `PartnerOrganisation` database models with automatic migrations.
  - [x] Open / Closed status filtering, custom ordering, and list-editable controls.
  - [x] Direct navigation shortcuts from Teklora Admin (`admin_base.html` and `admin_site_content.html`).

---

### 📚 Milestone 6: Staff Document Library & Permission-Aware AI *(Implemented in checkout; release acceptance pending)*

Specification: [Document library](specs/2026-11-04-document-library-spec.md). Agreed ACL & retrieval contract: [Library ACL & Retrieval Contract](specs/2026-11-07-library-acl-and-retrieval-contract.md). Team allocation and separate EduShare dashboard work: [Delivery plan](plans/2026-11-04-library-and-edushare-delivery-plan.md). First-wave tasks #32–#38 and #40 are assigned in production ([register](plans/2026-11-04-first-wave-task-register.md)).

- [x] Record user-approved library decisions and propose architecture, security gates, and cross-project task packets.
- [x] Confirm administrator mapping, external-processing review policy, document/OCR scope including DOCX meeting notes (no recording ingestion/transcription), 25 MB document/scan limit, and 30-day live deletion purge policy.
- [x] Create user-approved first-wave task assignments with repository links and dependency descriptions; hold Emmanuel.
- [x] **[Task #33] Library ACL & Retrieval Foundation (`knowledge_base/library/`)**: Defined canonical contracts, deny-by-default policy engine (`LibraryPolicy`), safe retrieval adapter (`LibraryRetrievalEngine`), and test stubs (`InMemoryLibraryStore`). Enforced zero provider calls without administrator clearance, no public retrieval without publication approval, and memory isolation against generic unscoped recall (`scope=None`). All unit/integration tests passing.
- [x] Document provider terms, restricted-data classification, document-processing worker capacity and backup expiry findings before processing is enabled (`docs/specs/2026-11-07-library-acl-and-retrieval-contract.md`).

Implementation gates below are tracked in the manually issued task packets and later scope proposals, not additional imported task assignments:

- [x] Add private document/version storage, per-document sharing, and administrator-only public review with audit history (Task #34 scope; implemented in checkout on 2026-11-12, not a task-board approval).
- [x] Add bounded asynchronous document OCR/extraction, chunking, embedding, retries, and version/deletion race protection (Task #34 scope; dedicated worker and scheduled purge).
- [x] Build library browse/upload/detail UI, sharing controls, processing indicators, and administrator review queue (Tasks #35 & #40 scope; `/library/`, linked from the panel).
- [x] Exercise automated access-control, public-revocation, upload/download, worker-race and lifecycle regression gates using isolated PostgreSQL/pgvector and fake providers.
- [x] Remove the library feature toggle entirely; staff navigation, pages, processing and public-approved retrieval are always available subject to existing authorization and review policies.
- [x] Redesign the complete library UI to match the admin theme: responsive browsing/review queues, upload/progress/errors, document preview/details/sharing and administrator decisions; verify desktop/mobile/light/dark and keyboard flows in a real local browser ([spec](specs/2026-11-12-library-ui-redesign-spec.md), [execution](plans/2026-11-12-library-ui-redesign-plan.md)).
- [ ] Complete real-worker OCR, production storage/backup-retention verification and security/operational sign-off. No live task statuses changed. See [completion plan](plans/2026-11-12-library-completion-plan.md).

---

## ✅ Completed Milestones

- [x] **Statutory Compliance & Legal Engine**: KDPA 2019 & GDPR compliant Privacy Policy and Terms of Service.
- [x] **Multi-Team Real-Time Email Broadcast**: Instant email alerts to all engineering inboxes for incoming client inquiries.
- [x] **Mail Attachments**: Staff can attach files to new mail and replies, and files received by email are kept and downloadable by whoever can read the conversation.
- [x] **Mail forwarding**: Forward any readable message, with a note and a choice of its attachments, from your own or a shared mailbox.
- [x] **Custom staff groups**: Create groups in the panel with capabilities, shared mailboxes and members, and invite people straight into them. Shared mailboxes are created in the panel instead of a hardcoded list.
- [x] **Capability-based mail access**: `view_inbox`, `handle_inquiries`, `view_all_mail` and `receive_inquiry_emails` decide who reads shared mail, replies, oversees personal mailboxes and is emailed inquiries.
- [x] **Staff & Role-Based Access Control**: Granular capability system with immutable audit logging.
- [x] **Staff Roster with Access Levels**: Derived Owner / Administrator / Member / No access levels, search and filters, and an editor that previews what a role combination grants.
- [x] **Partnerships & People in the Panel**: Partnership tracks, partners and job openings are managed from a themed panel page instead of Django admin.
- [x] **Staff Scope in Onboarding**: Staff pick the area of the business they work in (Marketing, Sales, Operations and others) at onboarding and can edit it, with their other details, from the dashboard profile.
- [x] **Multi-Assignee Task Board**: Status ladder (`Open` → `In Review` → `Done`) with per-assignee completion tracking.
- [x] **Cloudflare Tunnel & Dockerization**: Production-ready containerized deployment configuration.
