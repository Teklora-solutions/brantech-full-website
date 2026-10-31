# Changelog

All notable changes to the Teklora Solutions platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **AI Configuration & Touchpoints Hub (`/admin-panel/?section=ai`)**: Centralized LLM governance studio providing live provider connection status badges, per-token pricing indices, dynamic model catalogue browser, and touchpoint routing controls.
- **Dynamic Touchpoints Registry Pattern (`ai_workflows/harness/touchpoints.py`)**: Automatic registration pattern (`@register_touchpoint`) mapping any LLM invocation point in Django across agents/tasks to `AITouchpoint` database models, allowing operators to pin dedicated Providers and Models with custom fallback and temperature overrides.
- **Codex / ChatGPT Device Code Authentication**: Interactive device authorization flow invoking `https://auth.openai.com/codex/device` with one-time verification codes and background polling for seamless ChatGPT Plus/Pro subscription connections.
- **Google Cloud Vertex AI Adapter**: Added `VertexAIAdapter` supporting Google Cloud Service Account `.json` keys via `GOOGLE_APPLICATION_CREDENTIALS`, project IDs, and locations.
- **Unified Projects & GitHub Source Hub**: Unified repository management into the canonical Projects admin section (`/admin-panel/?section=projects`), replacing the fragmented standalone GitHub Manager view.
- **Dynamic Palette Extraction & Theme Harmonization**: Automatic sampling and derivation of vibrant brand accents and deep glow shades from uploaded project covers and screenshots, propagating dynamically across card glowing borders, showcase modules, and charts.
- **Media Attachments (Screenshots & Video)**: Extended `Project` model with direct video demonstration support (`video_url`, `video_file`) and enriched interface gallery management.
- **Interactive System Modules & Data Story Studio**: Replaced manual JSON Chart.js specifications with a visual metric comparison table builder and markdown README auto-extraction.
- **Single-Project GitHub Synchronization**: Added `POST /api/projects/<pk>/sync-github/` endpoint for 1-click on-demand commit and metadata refreshes directly from project cards.

### Changed
- **Admin Navigation Simplification**: Retired standalone GitHub Manager sidebar navigation in favor of in-line repository selection and sync inside the Projects workspace.
- **Documentation repair tasks**: Missing or invalid README.md, CHANGELOG.md, ROADMAP.md and LICENSE files automatically create unassigned repair tasks in Project backlog, using GitHub Manager’s existing document checks. Findings are grouped per file and refreshed without duplicates. Passing checks remove unassigned repairs from the backlog or submit assigned work for human review. Document pushes queue rechecks, and empty repositories still produce repair work.
- **GitHub task automation**: Referenced commits appear on task details; closing commits and task-branch merges submit assigned work for administrator review. Roadmap imports reuse GitHub-synced projects and populate an unassigned backlog. Includes Celery polling, an optional signed webhook, migrations and regression tests.
- **Custom staff groups with their own mailboxes and members**: Staff & Roles is now Staff & Groups. A group holds capabilities as before, plus shared mailboxes and members. From the group editor you tick its members, invite new people into it by email, tick the shared mailboxes its members read and reply from, and create a new mailbox on the spot. Group cards show members, pending invitations, mailboxes and capabilities. Members of a mailbox's groups are also emailed when mail arrives in it. `view_inbox` and `handle_inquiries` still reach every shared mailbox. Granting stays bounded: a non-superuser cannot add a capability they lack or a mailbox they cannot send from, cannot put anyone in a group that grants more than they hold, and cannot change their own or an owner's groups. Plan: `docs/plans/2026-10-27-custom-staff-groups-plan.md`.
- **Shared mailboxes are created in the panel**: the hardcoded `SHARED_MAILBOXES` list is gone. Mailboxes are `messaging.SharedMailbox` rows, listed under Staff & Groups → Groups with the groups using each and its conversation count, and created or deleted there (`/api/messaging/mail/shared/`, audited). Deleting one moves its conversations to Unmatched. Migration `messaging.0022` seeds the nine existing mailboxes with no groups, so nobody's access changes until a mailbox is added to a group. This supersedes the note below about editing `SHARED_MAILBOXES`.
- **Forward mail**: every message in the panel inbox has a Forward button. It opens the compose window with the original quoted under a "Forwarded message" header, an optional note, and the original's attachments ticked so you can leave any out; new files can be added too. It sends from your own address, or from a shared mailbox if you hold `handle_inquiries`, and files the forward as a new "Fwd:" thread there. Oversight readers forward from their own address, so nothing is written into a colleague's mailbox. Endpoint: `POST /api/messaging/mail/threads/<id>/forward/`.
- **Careers, jobs, hr, sales, billing and contact are shared mailboxes**: mail to these addresses used to land in Unmatched because only info@, hello@ and support@ were shared. Each now has its own shared mailbox for `view_inbox` holders, and appears as a campaign sender. Migration `messaging.0020` moves mail already in Unmatched to the right mailbox. To add another, add the name to `SHARED_MAILBOXES` in `staff/handles.py`.
- **Mail access is a capability again, so you decide who sees which email**: Staff & Roles now offers `view_inbox` (read shared mailboxes and inquiries), `handle_inquiries` (reply from them), `view_all_mail` (read-only oversight of every personal mailbox) and `receive_inquiry_emails` (be emailed inquiries, bookings and info@ mail), under Communications. An Administrator who was not a superuser previously saw only their own mailbox whatever their role said. No preset role carries them, so the original problem (every invited staff member reading info@) does not return; each grant is deliberate. Superusers hold all four implicitly, and notifications are still one message per person. Migration `staff.0021`; supersedes the superuser-only rule in the entry below.
- **GitHub Manager checks every repository for README.md, CHANGELOG.md, ROADMAP.md and LICENSE**: a repository missing one, or with a CHANGELOG or ROADMAP that does not follow the standard, gets an amber "N doc issues" badge on its card, appears under a new "Needs docs" filter, and its new Documents tab lists each file as OK, Needs fixing or Missing, with the exact problem and how to fix it. A misspelt license file (for example `LISENCE.md`) is named rather than reported as missing, and a roadmap in `docs/` is accepted. The format both files must follow is in `docs/specs/2026-10-20-repo-docs-standard-spec.md`; the checker is `brand/repo_docs.py`, and `open_roadmap_tasks()` produces the list of unchecked roadmap tasks that will feed manual task assignment. Results are cached for 6 hours and re-checked as soon as the repository is pushed to.
- **GitHub Manager says whether the key is a personal account or an organisation**: a banner shows the account that owns `GITHUB_ACCESS_TOKEN`, its token kind and its organisations (`/api/github/account/`), and warns if `GITHUB_USERNAME` is a different account. The current key is a classic personal access token for the user account `teklorasolutionsltd`, a member of the `Teklora-solutions` organisation.

### Fixed
- **Received attachments could be dropped**: the Mailgun route both forwards each email (files attached) and stores it with a notification (files listed by URL only), and both go to the inbound webhook. Whichever arrived first was kept, so an email whose store notification won was filed with its attachments shown as "not stored". The webhook now downloads the listed files from Mailgun's storage with the API key (`brandtechsolution/mailgun.py: stored_attachments`, Mailgun hosts only), so both posts bring the same files. If a download fails nothing is recorded and the webhook answers 503 so Mailgun retries.
- **Anyone could read, or take over, another visitor's website-chat conversation**: the chat trusted the conversation id sent by the browser. A signed-out visitor could ask for the history of any id, and a signed-in user who sent someone else's id was attached to that conversation. The server now decides which conversation a visitor is in: signed-out visitors always get the one in their own session, and signed-in users get only their own, so a sent id that is not theirs is ignored.
- **Bots aimed at the login page could slow sign-in for everyone and guess passwords without limit**: every attempt ran the deliberately slow password hash, up to three times for a wrong password, on the site's three web workers, and nothing counted failures. Now (`brand/login_throttle.py`):
  - A wrong password costs one hash, not two or three.
  - After 5 failures in 15 minutes from one address, or against one account, or 100 failures site-wide, each attempt must pass the Cloudflare Turnstile challenge. Attempts without it are refused before the password is checked, so a flood no longer queues real sign-ins.
  - After 30 failures in 15 minutes an address is refused outright (HTTP 429). No account is ever locked: the owner can always get in by solving the challenge, so nobody can lock a colleague out by guessing.
  - `/admin/login/` signs in through the same view, so Django admin's form is not a way around the limits.
  - The `next` parameter on login is checked, so a link to the login page can no longer redirect to another site after sign-in.
- **Other public endpoints a bot could hammer had no limits**:
  - **Password reset** (`/accounts/password_reset/`) sent an email for every request, so a script could fill any inbox through our Mailgun quota. It now needs the Turnstile challenge, refuses a network after 5 requests an hour, and sends at most 3 reset emails an hour to one address. The page still says the email is on its way when that limit is hit, so it never reveals which addresses have accounts. The "Forgot password?" links on the login pages now open it.
  - **Website chat** (`/api/ai/chat/`) made a paid model call for every message and held a web worker while it waited. It is now limited to 20 messages per 10 minutes per network (`CHAT_RATE_LIMIT_COUNT`, `CHAT_RATE_LIMIT_WINDOW_SECONDS`), and an error no longer sends the exception text to the visitor.
  - **Booking lookup** (`/appointments/get/`) returns a client's booking when id, email and phone match; it allows 10 lookups per 10 minutes per network and no longer echoes exception text. The **availability check** allows 60 per 10 minutes.
  - **Sign-up** allows 5 per hour per network, on top of the Turnstile challenge.
  - **Change password** in the panel allows 5 attempts per 15 minutes per account, so a stolen session cannot be used to guess the current password.
  - The test runner now empties the cache before every test, as the database already is, so rate-limit counts cannot carry over from one test to the next and fail tests depending on their order (`brandtechsolution/test_runner.py`).
- **People who used the "Sign up" link could never get into the panel**: both login pages linked to the public `/signup/` form, which creates ordinary non-staff accounts. The panel turned them away without a message, Staff & Roles could not find them, and inviting the same email was refused because the address was taken. Now:
  - The login pages say staff accounts are created by invitation instead of linking to sign-up.
  - Staff & Roles search finds sign-up accounts, marked "Signed up, not staff", and they have their own filter.
  - Sign-up is closed: `/signup/` now creates a deactivated account, and signing in to one says it is not active yet.
  - Login confirms a deactivated account's password only for sign-up accounts; a deactivated staff account gets the generic "invalid email/username or password" message, so a former employee's old password cannot be checked through the login page.
  - Anyone with `manage_staff` sees normal (non-staff) accounts in Staff & Roles, marked "Not staff yet".
  - Opening one sends a staff invitation to its address. Accepting it takes the account over with a new password, staff status and the invited roles. Sign-up never verifies the address, so the account is never made staff without proof the person holds that inbox, and the people API cannot edit sign-up accounts.
- **Staff could read shared mail and inquiries, and everyone was emailed every lead**: team invitations hand out the Support role, which carried `view_inbox` and `handle_inquiries`, so every staff member could read info@ and the other shared mailboxes. Every website inquiry, booking and email to info@ also went to the whole team's personal inboxes, including third-party mail such as account verification links. Now:
  - Each person sees only their own mailbox.
  - Shared mailboxes, mail to unclaimed addresses, website inquiries and oversight of other mailboxes are for superusers only, by a fixed rule in `messaging/mailbox.py` (`is_admin`) and `staff.permissions.IsSuperuser`.
  - Inquiry, booking and shared-mail notifications go to superusers only.
  - The `view_inbox`, `handle_inquiries` and `view_all_mail` capabilities are removed, and migration `staff.0020` deletes their grants, so no role can give this access again. The Support role keeps `manage_appointments`.
- **Staff notifications exposed everyone's personal address**: every capability-based notification (inquiries, bookings, shared mail, task reviews, editorial reviews, mail-limit notices, system alerts) was one message with every recipient on the To line. They are now sent as one message per person (`brandtechsolution.mail.send_mail_each`).
- **Pending migration warning on `brand`**: the flagship badge, solution label and solution description defaults on `SiteContent` were changed in `models.py` without a migration, so `manage.py migrate` reported unmigrated model changes. Migration `brand.0020` records them. Defaults only; no table changes.
- **Staff panel unreadable in light theme**: panel sections were written for dark mode with fixed classes (white text, white-tinted fills and borders, near-black inputs), so in light theme names, tabs and filters vanished and inputs stayed black. A new `panel-light.css`, loaded by `admin_base.html`, maps those classes onto the theme colours in light mode only (white text on solid buttons stays white). The panel's theme colours (`brand-blue`, `dark-card`, `surface` and others) are now wrapped in `color-mix`, so opacity modifiers such as `bg-brand-blue/10` draw instead of producing no colour. Five coloured messages that were `<p>` elements, which the shared stylesheet forces to grey, are now `div`s so warnings and errors show in colour.
- **Partnership track icon and colour ignored on the public page**: `/partnerships/` picked each card's icon by searching the track name for words such as "Academic" or "Tech". Cards now use the icon and accent colour set for the track in Partnerships & People, and the tagline shows in that colour.
- **Booking calendar unreadable in light theme**: the "Book a Strategy Session" modal on the contact page used `bg-surface/95` and `bg-surface/50`. Tailwind cannot add transparency to a colour defined as a CSS variable, so no background was drawn and dark text sat on the dark overlay. The card is now solid white (near-black in dark theme) and its inner panels use slate-50 / white-5%. The contact info cards and social tiles on the same page had the same see-through `bg-surface/50` and now use the solid `bg-surface` card colour.
- **"Partnerships & People" opened Access denied for administrators**: the link is shown to anyone holding Manage staff, but it opens Django admin, which checks per-model permissions that panel roles never carry, so only superusers got in. The Career, Partnership type and Partner organisation admin pages now allow staff who hold Manage staff, the same rule as Website Content.
- **Careers missing from stored header menus**: the header menu is saved in `SiteContent.header_links`, so sites created before the careers page never received its default link. Migration `brand.0019` adds "Careers & Jobs" to the About / Company submenu of each stored menu, and leaves a menu alone if it already links to `/careers/` or has no such submenu.

### Added
- **Close and reopen job openings and partnership tracks, hide and show partners**: in Partnerships & People, each partnership track has a one-click Close / Reopen button (closed tracks move to the archived list on `/partnerships/`) and each partner has Hide / Show, which takes it off or puts it back on the partners strip without deleting it. All three tabs share one POST-only view (`admin_partnership_status`), with the same permission as editing. Each job opening also has a Close / Reopen button and an Open/Closed status (also on the edit form and in Django admin). Closed roles leave `/careers/`, which shows a "No open roles right now" message when nothing is open. Migration `brand.0021` adds `Career.status` and `Career.closed_at`; existing roles stay open.
- **Applications-closed auto-reply**: an email that applies to a closed role gets an automatic reply saying applications have closed, sent from the role's address and filed in the same mailbox conversation (`messaging/autoreply.py`). The Apply link's subject now carries a `JOB-<id>` reference so the role is identified even when roles share an inbox; older subjects ("Application for <title>") are still matched. Each sender is told once per role, and machine senders (no-reply, mailer-daemon, `Auto-Submitted`, bulk/list mail, our own domain) are never answered. A notice is only sent when every `X-Mailgun-Spf` verdict in Mailgun's message-headers list is a pass and the envelope sender's domain matches the From domain, so a forged From address (or a forged verdict header) cannot aim it at someone who never wrote. Automatic replies are also capped at 50 an hour overall.
- **Attachments in staff mail** (`docs/plans/2026-10-18-mail-attachments-plan.md`): the panel mail client had no attachments anywhere. Compose and reply could not attach files, and files sent to us were thrown away, leaving only their names.
  - Compose and reply have an Attach button. Picked files show with their size and can be removed before sending. Limits are 10 files and 20 MB in total, and executable types (`.exe`, `.js`, `.bat` and others) are refused before sending because providers reject them. The API accepts `multipart/form-data` with `attachments` fields; JSON without files still works.
  - Files received through the Mailgun inbound webhook are now stored (new `MailAttachment` model, migration `messaging.0019`). An email to several mailboxes stores each file once. In the reader, attachments are download links. Mail received before this change still lists names only, marked "not kept".
  - Files are kept under `MAIL_ATTACHMENTS_ROOT` (default `brandtechsolution/private/mail_attachments`, Docker volume `./data/private`), never under the public `/media/`. `GET /api/messaging/mail/attachments/<id>/` serves them only to people who can read the conversation (others get 404), always as a download with `nosniff` and a sandbox CSP, so a received HTML or SVG file cannot run in the panel.
- **Partnerships & People page in the staff panel** (`/admin-panel/partnerships/`, `docs/specs/2026-10-12-partnerships-people-panel-spec.md`): the sidebar link used to open Django admin in a new tab. It now opens a panel page with tabs for partnership tracks, partner organisations and job openings, each with add, edit and delete. Forms validate Font Awesome icons, accent colours, http(s)-only links, logo size (2 MB) and job file type (PDF, DOC, DOCX up to 10 MB). Delete is POST-only with an on-page confirmation. Same access rule as Website Content; the page follows the panel's light and dark themes and works at phone width. The Website Content banner links here too; the Django admin pages stay as a fallback.
- **Themed access-denied page** (`403.html`): replaces Django's bare "403 Forbidden" for every permission failure, says whose account is signed in and who can grant access, and links back to the panel.
- **Area of work ("scope") in staff onboarding and profile** (`docs/specs/2026-10-12-staff-scope-onboarding-spec.md`):
  - New `StaffProfile.scopes` (migration `staff.0019`): the parts of the business a person works in, such as Marketing, Sales & Partnerships, Operations, or anything they type themselves.
  - Onboarding asks for at least one scope, offers non-engineering roles (Marketing Lead, Operations Manager and others), and collapses the languages, frameworks and GitHub fields into an optional "Technical skills" section that opens for Engineering and Product & Design.
  - The dashboard "My profile" form can now edit scope and bio as well as the existing details, using the same suggestions as onboarding (served as `options` by `GET /api/staff/me/`).
  - Staff & Roles shows each person's scopes and searches by them; `GET /api/staff/people/` includes read-only `scopes`.

### Changed
- **Persistent GitHub caching**: Repository lists, account details, document audits and text, READMEs and recent commits now use database snapshots across restarts. Normal GETs serve saved data and queue bounded background updates; unchanged revisions and file hashes avoid repeated downloads, and empty results remain cached. Refresh requests are capability-protected and coalesced, rate-limit responses establish a retry window, and failures retain last-good data. The UI shows update status without waiting on GitHub.
- **Roadmap backlog and assignment workspace**: Removed manual repository setup from Tasks. Existing GitHub-synced projects automatically supply roadmap items to a separate searchable backlog with project filters, import status and a dedicated assignment dialog. Imports leave staff unassigned; managers select owners through a capability-protected action that prevents conflicting assignments. Existing assignments are preserved, with the same API available to future authorized automation.
- **Careers address must be on our own domain**: new job openings default to `careers@<MAILBOX_DOMAIN>` instead of `careers@teklora.com`, the careers page footer uses the same address, and saving a role whose application address is on any other domain is refused (`Career.clean`, so the panel and Django admin both enforce it). Only mail that reaches the Mailgun inbound webhook can be auto-answered once a role closes.
- **Editorial pipeline consolidated into one app** (`docs/plans/2026-10-16-editorial-consolidation-plan.md`): the pipeline had been scaffolded as one Django app per "Module N" agent. Seven of those apps existed only to serve `editorial`, and most imported `editorial.models` back. `trends`, `research`, `seo`, `media_generation`, `analytics`, `approval` and `publishing` are now domains inside `editorial/`:
  - Models live in `editorial/models/<domain>.py`, views in `editorial/views/`, agents in `editorial/services/` (with `trends/` and `research/` sub-packages), the orchestrator, newsroom and Celery tasks in `editorial/pipeline/`, and tests in `editorial/tests/`.
  - `from editorial.models import X` and `from editorial.tasks import ...` still work, and Celery task names are unchanged.
  - Migrations: editorial's history is squashed into `0001_squashed_consolidation`, which existing databases treat as already applied. `0002` relabels the 11 moved models' content types to `editorial`, so permissions, admin history and memory documents stay attached. `0003` renames their tables from `trends_*`, `research_*` etc. to `editorial_*`. Row counts were verified unchanged on a copy of the dev database. Deploying needs only `manage.py migrate`.
  - `knowledge_base` stays its own app: it is the vector store used by `ai_workflows` beyond the newsroom.
- **Contact UI & Interactive Experience Refinement**:
  - Unified the visual language of [`contacts.html`](brandtechsolution/brand/templates/brand/contacts.html) with modern dark/light glassmorphic tokens, ambient glow gradients, and cohesive `#007AFF` / `#00FF94` brand palettes.
  - Re-architected interactive Strategy Calendar modal with dynamic date initialization (`new Date()`), real-time day/slot selections, and touch-optimized controls.
  - Aligned global footer container in [`footer.html`](brandtechsolution/brand/templates/brand/footer.html) with standard `max-w-7xl` layout and enhanced mobile responsiveness for columns, legal links, and copyright notices.
  - Sized and refined the Partnership Application modal card (`#applyModalCard`) in [`partnerships.html`](brandtechsolution/brand/templates/brand/partnerships.html) with compact bounds (`max-w-lg`, `max-h-[85vh]`), dynamic track badge pill, reduced form paddings, and smooth inner scroll container to eliminate oversized vertical height on mobile and desktop viewports.
  - Fixed overlay ordering for strategic consultation modals: raised `calendarModal` and `bookingModal` z-index to `2000` to sit above the glassmorphic header, and added semi‑transparent `bg-surface/95` (light) / `dark:bg-[#090D16]/95` (dark) to the booking card for clearer visibility in light mode.
- **Staff & Roles panel redesigned around access levels** (`docs/specs/2026-10-12-staff-roster-access-levels-spec.md`):
  - People roster shows each person's derived level (Owner, Administrator, Member, No access), role chips, last sign-in, and setup/deactivated status, with search and filter chips that carry counts.
  - Person editor shows what each role grants, a live preview of the resulting access, and explains why controls are locked (editing yourself or an owner) instead of failing on save.
  - Roles tab lists the capabilities each role grants and links to the people who hold it.
  - Invitations waiting are separated from the roster; the editor becomes a bottom sheet on phones.
  - `GET /api/staff/people/` now includes read-only `last_login`.

### Fixed
- **Contact Page Layout & Modal Hierarchy**:
  - Resolved malformed DOM hierarchy in [`contacts.html`](brandtechsolution/brand/templates/brand/contacts.html) where modal bodies, turnstiles, and scripts were fragmented outside the document body.
  - Eliminated duplicate Strategy Calendar CTA buttons and repaired modal backdrop, dismissal triggers, and keyboard `Escape` bindings.
- **Onboarding now reaches every staff member**: the gate in `staff/middleware.py` skipped any staff account with no `StaffProfile` row, which covered everyone who existed before onboarding shipped and anyone created through `createsuperuser` or `/admin/`. A missing profile now counts as not onboarded, the onboarding page creates it on first visit, and superusers without `is_staff` (admitted to the panel by `brand.views.is_admin`) are gated and can complete it too.

### Added
- **Dedicated Partnerships & CSR Page (`/partnerships/`)**:
  - Engineered standalone, glassmorphic Partnerships and Corporate Social Responsibility hub (`brand/templates/brand/partnerships.html`) showcasing active partnership tracks, collaborative workflow, CSR pillars, partner logos, and an interactive application modal.
  - Replaced all emojis, font icon glyphs, and bullet symbols with exact, crisp inline vector `<svg>` elements across all badges, lifecycle steps, track cards, benefit/requirement checklists, and CSR feature cards.
  - Implemented dynamic database models `PartnershipType` and `PartnerOrganisation` supporting real-time admin management for open/closed tracks, benefits, criteria, and partner organizations.
  - Dedicated CSR mandate to organizations touching the lives of children (orphanages, rescue shelters, digital literacy, child safety) and ministries spreading the Gospel of Jesus Christ (churches, missionary societies, congregation tools).
  - Clarified EduShare status across the platform: explicitly established that EduShare is not currently zero-rated, launching a public call and partnership track for telecommunications carriers (Safaricom, Airtel, MTN) and educational donors to sponsor student data and zero-rate syllabus access across Kenya's 47 counties and the African continent.
  - Positioned CSR under the Partnerships ecosystem and wired global header dropdown and footer quick links directly to `/partnerships/`.
  - Added full Django Admin management interfaces with list filtering, ordering, and quick-access management buttons from the Teklora Admin panel (`admin_base.html` and `admin_site_content.html`).
- **Company & Corporate Navigation Restructuring**:
  - Reorganized the global navigation and footer from "About" to "Company", housing all company dimensions: *About Us & Story*, *Mission & Values*, *Careers & Jobs* (`/careers/`), *CSR & Social Impact* (`/about/#csr`), and *Partnerships*.
  - Updated [about.html](brandtechsolution/brand/templates/brand/about.html) with a direct link and action card for open roles linking directly to the full [Careers Page](brandtechsolution/brand/templates/brand/careers.html).
- **Mobile Navigation Modal Popup & Dropdown Redesign**:
  - Transformed mobile dropdown into a sleek, floating glassmorphism popup modal with full-screen dimming blur backdrop.
  - Sized compactly (`max-width: 380px`, reduced paddings, concise fonts) so the popup fits comfortably on phone screens without feeling oversized.
  - Added dedicated popup header featuring brand logo, title, and intuitive close button (`<i class="fas fa-times"></i>`).
  - Implemented collapsible accordion cards for dropdown items with smooth rotate transitions and sublink icons.
  - Added quick-access theme switch pill (`Dark / Light Mode`) and high-contrast consultation CTA button.
  - Added backdrop click, `Escape` key dismiss, and automatic background scroll locking for phone UX.
- **Careers Page & Admin Management Specification**:
  - Authored comprehensive specification ([`2026-10-11-careers-page-admin-management-spec.md`](docs/specs/2026-10-11-careers-page-admin-management-spec.md)) detailing the `JobOpening` model architecture, dynamic querying, and `/admin-panel/?section=careers` management hub.
  - Added Milestone 4 to [ROADMAP.md](docs/ROADMAP.md).
- **Staff GitHub Repository Scanning & Permission Discovery**:
  - Automatically scan repositories owned by staff members configured via `StaffProfile.github_username`.
  - Filter repositories to only include those where the platform's authenticated GitHub account has access (push/write, admin, maintain, or private pull access).
  - Categorize staff repositories with `role="staff"` and attach staff member attribution metadata (`username`, `staff_name`, `primary_role`).
  - Added dedicated `Staff` filter tab, metric badge counters, and owner chips in GitHub Manager admin dashboard (`/admin-panel/?section=githubSync`).
  - Synced staff projects automatically save with `github_role="staff"`.
- **Staff Onboarding & Capabilities Engine**:
  - Interactive onboarding wizard (`/staff/onboarding/`) prompting staff for WhatsApp number, primary engineering role, programming languages, and frameworks.
  - Comprehensive technology catalog covering AI/Computer Vision (OpenCV, PyTorch, Whisper, Gemini, RAG), Web & Backend (Django, FastAPI, Flask, DRF, Next.js, HTMX), Automation & Bots (Playwright, Browser-Use, WhatsApp/Telegram APIs, n8n), and Mobile/Desktop (Flutter, Android SDK, PySide6/Qt, Tauri).
  - Automatic Kenyan & international phone normalization to E.164 (`+254...`) with `wa.me` integration in the Admin panel.
  - Extended `StaffProfile` with `coding_languages`, `frameworks`, `primary_role`, `github_username`, `bio`, and `is_onboarded`.
  - Updated `MeSerializer` and Admin User Profile modal with real-time capability viewing and editing.
  - Onboarding gatekeeper middleware ensuring invited staff complete setup before navigating the panel.
- **Repository Engineering & Agent Infrastructure**:
  - `AGENTS.md` canonical instructions for AI pair-programming and autonomous workflows.
  - Universal symlinks for AI agents (`.cursorrules`, `CLAUDE.md`, `GEMINI.md`, `.agentrules`, `.github/copilot-instructions.md`).
  - `docs/ROADMAP.md` and `CONTRIBUTING.md` developer workflow guidelines.

---

## [1.2.0] - 2026-09-28

### Added
- **Lawyer-Grade Statutory Compliance Pages**:
  - Privacy Policy page (`/privacy/`) compliant with KDPA 2019 and GDPR.
  - Master Terms & Conditions page (`/terms/`) with dispute resolution under NCIA rules.
- **Multi-Recipient Notification Broadcasting**:
  - Site-wide contact inquiries and appointment bookings broadcast in real-time to all core engineering and executive inboxes.
- **Site-Wide AI Chatbot Assistant**:
  - Reusable glassmorphic AI chatbot widget embedded across all public page layouts.

### Changed
- **Admin Inbox Streamlining**: Converted inquiry cards to display-only view with copyable contact badges.
- **Admin Appointments View**: Cleaned appointment cards to prioritize client names and direct calendar management.

---

## [1.1.0] - 2026-08-04

### Added
- **Staff & Roles Management Engine (`staff`)**:
  - Granular capability-based permission system with audit logging and invitation tokens.
- **Multi-Assignee Task Tracking Pipeline (`tasks`)**:
  - Real-time task board with priority sorting, assignment completion tracking, and review approval workflows.
- **Email Campaign & Template Authoring Engine (`messaging`)**:
  - HTML email template builder and campaign audience segmentation.

---

## [1.0.0] - 2026-05-29

### Added
- Initial enterprise Django release of the Teklora Solutions platform.
- AI newsroom and automated editorial pipeline.
- Dockerized container setup and Cloudflare Tunnel routing.
