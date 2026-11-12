# Teklora Solutions Fullstack Platform

This repository contains the enterprise Django web application for **Teklora Solutions Ltd** (formerly Brantech Solution) — a modern, high-performance platform for AI technology, software engineering, digital transformation, and technical consultation.

---

## Staff Document Library & Retrieval Infrastructure

The staff document library supports private research/meeting documents, per-document sharing, background embedding, and administrator-only approval for public-facing AI use. Embedding readiness does not grant public access.

- [Library specification](docs/specs/2026-11-04-document-library-spec.md)
- [Library ACL & Retrieval Contract](docs/specs/2026-11-07-library-acl-and-retrieval-contract.md)
- [Team task plan — Teklora library and EduShare student/admin dashboards](docs/plans/2026-11-04-library-and-edushare-delivery-plan.md)
- [First-wave task register](docs/plans/2026-11-04-first-wave-task-register.md)

**Implementation (Tasks #33–#35 and #40):** Staff pages at `/library/` now provide private upload, permission-filtered search, extracted previews, authenticated downloads, replacement versions, per-person/group/organisation sharing, processing clearance and a separate public-review queue. The panel sidebar always links to **Knowledge Library** for staff. Documents are private by default; only active superusers or active staff in `Administrator` with `approve_library_publication` may approve processing/public use. Metadata edits, replacements, revocation and deletion immediately remove public eligibility.

### Library configuration and operations

- The library is always available to authenticated active staff; there is no feature toggle or enablement environment variable. Document ACLs, administrator processing clearance and separate public-use approval remain mandatory.
- `LIBRARY_STORAGE_ROOT` defaults to `brandtechsolution/private/library`, **outside public media/static roots**. Web, dedicated library worker and default maintenance worker must share this persistent private mount. Originals have random keys and no public URL; downloads are authenticated attachments.
- Supported: PDF, DOCX (including externally generated meeting notes), UTF-8 TXT/Markdown, PNG/JPEG scans. Maximum 25 MiB, 30 PDF pages, 10 MiB extracted text, 500 chunks. Audio/video ingestion is not supported.
- Local OCR uses `tesseract` and `pdftoppm` (installed by the Docker image). No external OCR provider is used. Extraction/OCR/embedding runs on the dedicated `library_processing` queue, with a prefork worker capped at concurrency 2 and 55s soft/60s hard execution limits. Outside Docker, install Tesseract and Poppler and run `celery -A brandtechsolution worker -Q library_processing --concurrency=2` alongside the ordinary worker/Beat.
- Run `python manage.py migrate` as part of deployment. Docker Compose includes `library-worker` and shared private volumes. Gemini embeddings require approved standard-data clearance, `GOOGLE_API_KEY`, and an active `EmbeddingSpace` matching the configured embedding model/provider. Restricted personal/financial data is blocked. Parser/provider failures remain visibly failed, never ready; retries are bounded and interrupted jobs become retryable.
- Beat runs library maintenance every 15 minutes: deleted documents are inaccessible immediately and their live originals/chunks/vectors are purged promptly, within the 30-day deadline. **Verify actual database/file backup retention separately**; this repository does not prove backup expiry. Already delivered answers/downloads cannot be withdrawn.
- `LibraryRetrievalEngine.retrieve` provides ACL-filtered lexical retrieval; `retrieve_semantic` ranks only joined, eligible current-version chunks in the active embedding space. All generic `Memory.recall` paths exclude library scopes, even when explicitly named. Public assistant/newsroom tool suites include `search_public_library`, which can only read administrator-approved ready current versions. No private content is added to public chat.
- The internal library tool factory binds a trusted server-side actor, refreshing activation and grants each call. Do not attach it to shared/public chat, persist private results in shared sessions, or enable body/tool-result tracing for an internal caller. Private document embedding calls disable LangSmith tracing.

See the [completion plan](docs/plans/2026-11-12-library-completion-plan.md). Test with an isolated PostgreSQL/pgvector database and stub providers: `cd brandtechsolution && python manage.py test knowledge_base ai_workflows staff tasks`. No production migration, task-board completion or deployment is implied by the checkout implementation.

## ⚡ Recent System Enhancements & Release Notes

### ⚖️ Lawyer-Grade Legal & Statutory Compliance Framework
- **Privacy Policy Page** (`/privacy/` | `brand/templates/brand/privacy.html`):
  - Drafted under expert legal standards complying with the **Kenya Data Protection Act 2019 (KDPA)** and the **EU General Data Protection Regulation (GDPR)**.
  - Formatted into clean glassmorphic cards detailing Data Controller identification, legal processing bases (KDPA Sec. 30 & GDPR Art. 6), AES-256/TLS 1.3 encryption, 90-day telemetry retention, and Data Subject Access Request (DSAR) protocols.
- **Master Terms & Conditions Page** (`/terms/` | `brand/templates/brand/terms.html`):
  - Binding Master Service Agreement detailing Statements of Work (SOW), Intellectual Property assignment (Client Deliverables vs. Teklora Background IP), acceptable use policies, Net 30 payment schedules, liability caps, and dispute resolution via binding arbitration under the Nairobi Centre for International Arbitration (NCIA).

### 📬 Multi-Recipient Team Email Broadcasting
- Enhanced both contact inquiry submissions (`contact_submit`) and calendar consultation bookings (`create_appointment`) to automatically broadcast real-time notification emails to all 5 team email addresses simultaneously:
  - `juniorkariuki735@gmail.com`
  - `mugishalionel02@gmail.com`
  - `teklorasolutionsltd@gmail.com`
  - `leonmusungu138@gmail.com`
  - `davidnjihia536@gmail.com`

### 🎨 4-Column Footer & Global Chatbot Integration
- **Redesigned Footer**: Silicon Valley 4-column structure featuring company branding, social links (LinkedIn, Facebook, TikTok, Instagram), Quick Links, Services, Contact details, and explicit legal links (`/privacy/` and `/terms/`).
- **Updated Contact Email**: Global official email updated to `teklorasolutionsltd@gmail.com` across footer, contact page, privacy policy, and terms pages.
- **Site-Wide AI Chatbot Assistant**: Embedded reusable `chatbot.html` widget included inside `footer.html` for site-wide inheritance across all public pages.

### 📊 Admin Panel Restructuring
- **Display-Only Inbox**: Restructured inquiry cards to highlight client avatar badges, full name, mailto email link, tel phone link, timestamp, and message body; removed action buttons to focus on display.
- **Clean Appointments View**: Streamlined appointment cards by removing pending status pills, duration tags ("30 min"), and test titles, setting the Client's Full Name as the primary header.
- **Admin Sidebar Optimization**: Removed redundant Projects navigation link from the admin sidebar.

---

## 🚀 Key Features Overview

- **Silicon Valley Styled Portfolio & Services**: Modern, glassmorphic UI showcasing enterprise products, solutions, research, and technical services.
- **AI Content Scraping & Editorial Publishing Pipeline**: Automated content curation, AI-assisted article generation, markdown parsing, and capability-gated publishing.
- **Streamlined Appointment Booking System**: Virtual strategy consultation scheduling with real-time calendar availability checking and multi-recipient team notifications.
- **Multi-Recipient Notification Broadcasting**: Automatic notification dispatch to key team members on contact inquiries and consultation bookings.
- **Global AI Chatbot Assistant**: Embedded RAG-enabled floating chat widget powered by Google Gemini and ChromaDB vector embeddings.
- **Capability-Based Staff & Admin Control**: Fine-grained role-based access control (RBAC), security audit logs, staff invitations, and an interactive admin dashboard.
- **Legal & Compliance Infrastructure**: Market-standard, lawyer-drafted Privacy Policy (GDPR & Kenya Data Protection Act 2019 compliant) and Master Terms & Conditions.
- **Mobile-First Responsive Design**: Dynamic glassmorphism, responsive navigation menus, and adaptive card layouts for all screen sizes.

---

## 🤖 AI Editorial: Content Scraping & Publishing Pipeline

The platform includes an automated AI Editorial engine (`editorial/` & `ai_workflows/`) that automates content curation and publication:

```
┌──────────────────────────┐    ┌──────────────────────────┐    ┌──────────────────────────┐
│  Scrape & Discover       │───>│  AI Processing &         │───>│  Draft Review &          │
│  Industry Trends         │    │  Markdown Generation     │    │  Capability Publishing   │
└──────────────────────────┘    └──────────────────────────┘    └──────────────────────────┘
```

1. **Content Discovery & Scraping**: Ingests industry RSS feeds, technology trends, and engineering research topics.
2. **AI Content Generation**: Leverages Google Gemini and custom prompt pipelines to draft structured technical articles formatted in GitHub-flavored Markdown.
3. **Draft & Moderation Stage**: Generated posts enter the database as `draft` status, allowing editorial teams to review, edit, or approve.
4. **Capability-Gated Publishing**: 
   - Users with `manage_blog` can create and edit post contents.
   - Users with `publish_blog` can transition posts from `draft` to `published`, making them instantly available on the public site and updating the vector store embeddings.

The whole pipeline is one Django app, with each agent's domain kept apart by package rather than by app:

| Path | Contents |
|---|---|
| `editorial/models/` | One module per domain: `article`, `trends`, `research`, `social`, `media`, `approval`, `publishing`, `analytics`, `memory`, `runs` |
| `editorial/services/` | The agents: `trends/`, `research/`, `strategy`, `writer`, `seo`, `visual`, `social`, `approval`, `publishing`, `analytics`, `memory` |
| `editorial/pipeline/` | `orchestrator`, `newsroom` (the supervisor-facing agent) and the Celery `tasks` |
| `editorial/views/`, `admin/`, `tests/` | Split by the same domains |

A new agent goes into `editorial/services/` with its models in `editorial/models/`, not into a new app. The vector store (`knowledge_base/`) is a separate app because `ai_workflows` uses it beyond the newsroom.

---

## 📅 Streamlined Appointment Booking System

The appointment module (`appointments/`) provides an intuitive scheduling workflow for virtual strategy sessions:

- **Real-Time Availability Checking**: The `/appointments/check-availability/` endpoint validates date, time, and duration against active bookings to prevent overlapping slots.
- **Display-Only Admin Management**: Restructured admin list interface displaying Client Name, Email (clickable `mailto:`), Phone (clickable `tel:`), Date, Time, and Created timestamp without unnecessary buttons or test clutter.
- **Multi-Recipient Notification System**: Every booking automatically dispatches a real-time notification email to the primary admin and team members:
  - `juniorkariuki735@gmail.com`
  - `mugishalionel02@gmail.com`
  - `teklorasolutionsltd@gmail.com`
  - `leonmusungu138@gmail.com`
  - `davidnjihia536@gmail.com`

---

## 🎨 Complete Frontend Re-Engineering & Design System

The platform has undergone a complete architectural redesign for high visual impact and enterprise appeal:

- **Silicon Valley Design Aesthetic**: Built with modern dark mode (`#06090F`), smooth gradients, glassmorphism (`backdrop-filter: blur`), dynamic hover effects, and custom typography (Google Fonts *Inter* & *Outfit*).
- **4-Column Responsive Footer**: Includes company branding, social channels, Quick Links, Services, and direct legal links (`/privacy/` and `/terms/`).
- **Global AI Chatbot Widget**: Standalone reusable template (`chatbot.html`) included globally across all frontend pages via `footer.html`.
- **Lawyer-Drafted Legal Framework**:
  - **Privacy Policy** (`/privacy/`): Formatted under the **Kenya Data Protection Act 2019 (KDPA)** and **EU GDPR**, detailing Data Controller roles, legal processing grounds, AES-256/TLS 1.3 encryption, and Data Subject Access Request (DSAR) rights.
  - **Terms & Conditions** (`/terms/`): Formal Master Service Agreement covering Intellectual Property demarcation, acceptable use policies, payment schedules (Net 30), liability caps, and arbitration under the Nairobi Centre for International Arbitration (NCIA).

---

## 📱 Mobile Responsiveness & Adaptive UX

- **Fluid Grid Layouts**: Adaptive 1-column mobile layouts transitioning smoothly to multi-column desktop grids across forms, cards, and footers.
- **Mobile Navigation Drawer**: Responsive slide-over hamburger menu with smooth transitions for mobile viewports.
- **Collapsible Admin Sidebar**: Collapsible navigation bar with state persistence stored in `localStorage` for personalized workspace views.
- **Touch-Optimized Calendar**: Mobile-friendly date and time slot pickers with large touch targets.

---

## 🛠️ Technology Stack

- **Backend**: Django 5.2.7 (Python 3.13)
- **Database**: PostgreSQL with `pgvector` / SQLite (development)
- **Background jobs**: Celery (worker + beat) with Redis as broker and result backend
- **Cache**: Redis (falls back to local memory when no Redis is configured)
- **AI / ML**: Google Gemini API, LangChain, LangGraph
- **Vector Database**: ChromaDB / PGVector
- **Styling**: Custom Vanilla CSS Design System (`redesign.css`) + Tailwind CSS (utilities)
- **API**: Django REST Framework

---

## 🤖 Developer Portal, Agent Auto-Setup & MCP Server

Teklora integrates native support for human software engineers and autonomous AI coding agents:

- **Developer API Keys & Agent Setup (`/admin-panel/?section=developer`)**: Staff members can view the one-click auto-setup link, copy reference agent configurations for Claude Code, Cursor, Windsurf, and Antigravity, and review instructions on obtaining API keys (`tkl_live_...`). Keys are managed securely via Django Admin with SHA-256 hashes.
- **One-Click Agent Auto-Setup Link (`/developer/setup/`)**: Developers can copy an auto-setup URL or prompt to paste into their favourite agent (Claude Code, Cursor, Google Antigravity, Windsurf, Cline). The endpoint renders instructions on: (1) downloading the Teklora Developer Skill, (2) configuring the MCP Server, (3) receiving platform updates, and (4) guiding the user on setting their API key.
- **Zero-Dependency Teklora Developer MCP Server (`brandtechsolution/scripts/teklora_mcp.py`)**: A standard JSON-RPC 2.0 stdio Model Context Protocol server exposing task management (`teklora_list_my_tasks`, `teklora_get_task_details`, `teklora_complete_task_assignment`), developer profiles (`teklora_get_developer_profile`), repository listings, and semantic knowledge search.
- **Canonical Developer Skill (`skills/teklora-developer/SKILL.md`)**: Defines git branch standards (`<type>/<task-id>-<slug>`), Conventional Commits with task references (`feat(staff): [Task #41] ...`), the "Every Update" file maintenance contract, and the platform task ladder.

---

## 🛠️ Project Setup Guide

### Prerequisites

- Python 3.10+
- Virtual environment (`venv`)

### 1️⃣ Clone & Setup Environment

```bash
git clone https://github.com/jameskariuki8/brantech-full-website.git
cd brantech-full-website/brandtechsolution

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2️⃣ Environment Configuration

Copy `env.example` to `.env` and configure your credentials:

```ini
SECRET_KEY=your-secret-key-here
GOOGLE_API_KEY=your-google-gemini-api-key
DEBUG=True
ALLOWED_HOSTS=["127.0.0.1","localhost"]
```

### 3️⃣ Database & Vector Store Initialization

```bash
# Run database migrations
python manage.py migrate

# Initialize AI Vector Stores (Gemini embeddings)
python manage.py init_vector_stores

# Run development server
python manage.py runserver
```

Visit: **http://127.0.0.1:8000/**

---

## 🔌 Core API Endpoints

### Blog & Content API
- `GET /api/posts/` - List published blog posts
- `POST /api/posts/` - Create a blog post (`manage_blog` required)
- `GET /blog/<slug>/` - Server-rendered blog detail page

### AI Chatbot API
- `POST /api/ai/chat/` - Interactive RAG chatbot endpoint
- `GET /api/ai/chat/history/` - Retrieve session history

### Appointments API
- `POST /appointments/create/` - Book virtual consultation
- `POST /appointments/check-availability/` - Validate available slots
- `GET /appointments/` - Admin appointments list view (`manage_appointments` required)

### Contact & Messaging API
- `POST /contacts/submit/` - Public contact form submission (triggers multi-recipient email notifications)

---

## 🧪 Testing

```bash
# Run all test suites
python manage.py test

# Run specific app tests
python manage.py test messaging.tests.test_contact_submit
python manage.py test messaging.tests.test_inbox_escaping
python manage.py test appointments
```

---

## 🚀 Deployment

### Production Checklist

1. Set `DEBUG=False` in `.env`
2. Set a strong `SECRET_KEY`
3. Configure `ALLOWED_HOSTS` with your domain
4. Set up PostgreSQL database
5. Configure email settings for production
6. Collect static files: `python manage.py collectstatic`
7. Set up proper media file serving
8. Configure environment variables on your server

### Upgrading an existing deployment: staff roles

This release adds migrations for the new `staff` app and a `status` field on
`BlogPost`. Run `python manage.py migrate` on deploy. The blog migration
backfills every existing post to `published`, so nothing disappears from the
public site. No new Python dependencies are added, so a plain container
restart is sufficient once migrations have run. (Under Docker Compose the
`web` entrypoint already runs `migrate` for you.)

The staff migration also creates the four preset roles. See
[Staff roles and permissions](#staff-roles-and-permissions) for what they
grant and how to invite people.

### Environment Variables for Production

```bash
DEBUG=False
SECRET_KEY=your-production-secret-key
ALLOWED_HOSTS=["yourdomain.com","www.yourdomain.com"]
DATABASE_ENGINE=postgresql
DATABASE_NAME=brantech
DATABASE_USER=your-db-user
DATABASE_PASSWORD=your-db-password
DATABASE_HOST=localhost
DATABASE_PORT=5432
GOOGLE_API_KEY=your-google-api-key
```

## 📚 Documentation

- [AI Workflows README](brandtechsolution/ai_workflows/README.md) - Detailed documentation for the AI chatbot integration
- [LangChain Integration Docs](docs/langchain-quick-start-guide.md) - Quick start guide for LangChain

## 🐳 Running with Docker (behind Cloudflare Tunnel)

The stack runs three containers — `db` (Postgres + pgvector), `web`
(gunicorn + WhiteNoise), and `cloudflared` (Cloudflare Tunnel) — with **no host
ports published**. Inbound traffic arrives only through the tunnel; `cloudflared`
dials the Cloudflare edge outbound and proxies to `web` over the internal network.

Persistent data lives in the in-project `./data/` directory (`./data/postgres`,
`./data/media`), which is gitignored.

### 1. Configure environment

Two gitignored files at the **repo root** (next to `docker-compose.yml`):

- **`.env`** — app + database config, based on `brandtechsolution/env.example`.
  For Docker, set `DATABASE_HOST=db` and `DEBUG=False`, and set `ALLOWED_HOSTS`
  and `CSRF_TRUSTED_ORIGINS` to your real domain — `CSRF_TRUSTED_ORIGINS` (with
  the `https://` scheme) is **required** behind the tunnel or form/admin POSTs
  return HTTP 403. Compose injects these as real environment variables
  (pydantic-settings reads them directly — no in-container `.env` file is
  required or baked into the image).
- **`cloudflared.env`** — contains only the tunnel token, kept separate so it
  never enters the web container's environment or the process command line:

  ```
  TUNNEL_TOKEN=your-cloudflare-tunnel-token-here
  ```

### 2. Create the Cloudflare Tunnel

In the Cloudflare Zero Trust dashboard → Networks → Tunnels, create a tunnel,
add a **public hostname** routing your domain to `http://web:8000`, and copy the
tunnel **token** into `cloudflared.env`.

### 3. Build and run

```bash
docker compose up -d --build
```

The `web` entrypoint runs `migrate` and `collectstatic` automatically, then
starts gunicorn.

> **First run / changing DB credentials:** Postgres initializes its data
> directory only once. If `./data/postgres` already exists, it ignores new
> credentials in `.env`. To start fresh, stop the stack and remove the directory
> (`docker run --rm -v "$(pwd)/data:/data" alpine rm -rf /data/postgres`).

### 4. One-off management commands

```bash
# Create an admin user
docker compose exec web python manage.py createsuperuser

# Build vector embeddings for blog posts/projects (uses the Gemini API)
docker compose exec web python manage.py init_vector_stores
```

## Background jobs (Celery)

Work that takes longer than a request should runs on Celery rather than in the
web process. The editorial pipeline is the reason: it makes eight sequential
Gemini calls and takes around three minutes, so running it inline meant the
Cloudflare tunnel closed the connection at its 100-second limit and handed the
browser an HTML error page where it expected JSON — while the run carried on to
completion, invisibly. The dashboard now queues a run and polls it.

### Services

| Service  | Command      | Role                                             |
|----------|--------------|--------------------------------------------------|
| `redis`  | -            | Broker (db 0), results (db 1), Django cache (db 2) |
| `worker` | `worker`     | Executes all tasks                                |
| `beat`   | `beat`       | Fires the scheduled jobs. **Never run more than one.** |

`entrypoint.sh` dispatches on its first argument, so all three roles share one
image. Only the `web` role runs `migrate` and `collectstatic`.

### Registered tasks

| Task                                  | Trigger                        |
|---------------------------------------|--------------------------------|
| `editorial.run_pipeline`              | Dashboard button               |
| `editorial.index_article_embeddings`  | On publish (retried w/ backoff) |
| `editorial.release_stale_pipeline_runs` | Beat, nightly 02:30          |
| `messaging.process_email_outbox`      | Beat, every `BEAT_OUTBOX_INTERVAL`s |
| `brand.sync_github`                   | Beat, every `BEAT_GITHUB_SYNC_INTERVAL`s |
| `brand.rebuild_vector_stores`         | On demand                      |

### Watching a run

```bash
docker compose logs -f worker
docker compose exec web python manage.py shell -c \
  "from editorial.models import EditorialPipelineRun as R; print(R.objects.first().__dict__)"
```

### Working without Redis

Set `CELERY_TASK_ALWAYS_EAGER=true` in `.env`. Tasks then execute inline in the
calling process - the pipeline blocks its request again, but nothing silently
never runs. The test suite forces this on regardless, so tests never need a
broker.

### Notes on the configuration

- `task_acks_late` + `worker_prefetch_multiplier=1`: a three-minute run must
  survive its worker being killed, and a worker must not sit on tasks it cannot
  start.
- `task_reject_on_worker_lost` is deliberately **off** for the pipeline. It is
  not idempotent enough to auto-replay - a blind retry would re-research the
  same topics and double the model spend - so a lost run is failed by the
  nightly sweep instead.
- Redis runs with `maxmemory-policy noeviction`: evicting a key under memory
  pressure would silently drop a queued task.
- Prefork pool, not gevent. The tasks are I/O-bound on the Gemini API, but
  psycopg2 and LangChain underneath do not monkey-patch cleanly.

---

### Notes

- Static files are served by WhiteNoise; user-uploaded media is served by Django
  (`CompressedStaticFilesStorage` is used rather than the strict manifest variant
  because some bundled CSS references a missing asset).
- The `web` container runs as root to keep the bind-mounted `./data/media`
  writable regardless of host UID.

## Email delivery

Everything outbound goes through Mailgun's HTTP API via a Django email
backend (`brandtechsolution/mailgun.py`). Because it is a backend and not a
separate send path, `send_mail()`, the bulk outbox and every other caller are
unchanged; swapping providers again means changing `EMAIL_BACKEND` and nothing
else.

| Variable | Purpose |
|---|---|
| `MAILGUN_API_KEY` | Private API key. Selects the Mailgun backend when set alongside the domain. |
| `MAILGUN_DOMAIN` | Verified sending domain, e.g. `mg.teklora.co.ke`. |
| `MAILGUN_BASE_URL` | API root only — **not** the per-domain path. EU accounts use `https://api.eu.mailgun.net/v3`. |
| `DEFAULT_FROM_EMAIL` | Public From address. Defaults to `noreply@$MAILGUN_DOMAIN`. |
| `EDITORIAL_REVIEW_EMAIL` | Optional fallback only — see below. |
| `EMAIL_TIMEOUT` | Per-request timeout on the Mailgun call. |
| `MAIL_ATTACHMENTS_ROOT` | Where staff mail attachments are stored. Defaults to `brandtechsolution/private/mail_attachments`. Keep it outside `MEDIA_ROOT`, which is served publicly; Docker mounts `./data/private` here. |

Staff mail supports attachments in both directions. Files received through the
inbound webhook are kept, and compose and reply accept up to 10 files totalling
20 MB, with executable types refused. Downloads go through
`/api/messaging/mail/attachments/<id>/`, which applies the same access rule as
the conversation itself.

The Mailgun route both forwards each email and stores it with a notification,
and both reach the webhook. The stored-notification post lists files by URL
only, so the webhook fetches them from Mailgun storage with `MAILGUN_API_KEY`;
either post files the message with its attachments.

Any message a person can read can be forwarded
(`/api/messaging/mail/threads/<id>/forward/`). It goes out from a mailbox they
may send from (their own, or a shared one with `handle_inquiries`), quotes the
original under a "Forwarded message" header, carries whichever of its stored
attachments they keep, and is filed as a new thread in the sending mailbox.

The From address must sit inside the sending domain. Anything else — a
`gmail.com` address in particular — fails SPF and DKIM alignment and lands in
spam, which is why the previous hardcoded Gmail fallbacks were removed.

Backend selection is Mailgun → SMTP → console, in that order. The console
backend prints mail to stdout and reports it as sent, so a misconfigured
deployment would march a campaign through every recipient marking them
delivered while nothing left the building. A system check
(`mailgun.check_email_configured`) refuses to start if it is ever selected
with `DEBUG` off — the same guard, for the same reason, as the Turnstile one.

SMTP remains available as a fallback for development. It is not a route for
campaign mail: Gmail caps a consumer account near 500 recipients/day and
Workspace near 2,000, which the outbox exhausts in minutes at its defaults.

### Who gets notified

Staff notifications are addressed by capability, not by configuration.
`staff.emails.capability_holder_emails(codename)` resolves the capability to
the accounts that currently hold it — directly, through a role group, or by
being a superuser — filtered to active staff with an address, which is exactly
what `User.has_perm()` and `staff.decorators` consult. Granting or revoking a
capability in the panel therefore changes who is notified, with nothing to keep
in step by hand.

| Notification | Sent to |
|---|---|
| Contact form inquiry | `receive_inquiry_emails` |
| Mail to a shared mailbox (info@, careers@, ...) | `receive_inquiry_emails`, and the members of the groups that hold that mailbox |
| Strategy session booking | `receive_inquiry_emails` |
| Task ready for review | `manage_tasks` |
| Editorial draft ready for review | `publish_blog` |

`EDITORIAL_REVIEW_EMAIL` is consulted only when nobody holds `publish_blog`
yet, so a fresh deployment's first drafts are not reviewed by nobody; once a
single account has the capability the fallback is never used. Note that
superusers hold every capability implicitly, so they receive all of these.

Every notification is sent as a separate message to each recipient, so no one
sees another person's address.

### Mail access

Each staff member reads their own mailbox (`<handle>@` the mail domain) and
nothing else unless granted more.

**Shared mailboxes** (info@, careers@, hr@, ...) are created and deleted under
**Staff & Groups → Groups → Shared mailboxes** (`messaging.SharedMailbox`,
`/api/messaging/mail/shared/`); there is no list to edit in code. Adding a
mailbox to a group lets that group's members read it and reply from it, and
emails them when mail arrives. Deleting a mailbox moves its conversations to
Unmatched. A mailbox's name cannot be a staff handle or a mail-system address
(postmaster, abuse, ...), and nobody can pick a shared mailbox's name as their
handle.

Four capabilities reach further, and no preset group carries them, so each is a
deliberate grant to a group or a person:

| Capability | Gives |
|---|---|
| `view_inbox` | Read every shared mailbox, mail to unclaimed addresses and website inquiries |
| `handle_inquiries` | Reply, file and send from every shared mailbox; answer inquiries |
| `view_all_mail` | Read-only oversight of every staff member's mailbox |
| `receive_inquiry_emails` | Be emailed website inquiries, bookings and info@ mail |

Superusers hold all four implicitly.

### Team seeding

These notifications used to go to five email addresses hardcoded in
`messaging/views.py` and `appointments/views.py`. That made the roster a deploy
artefact — somebody leaving kept receiving customer names and phone numbers
until a developer edited Python, somebody joining received nothing until the
same happened, and one mistyped address survived in both copies because fixing
one did not fix the other.

`manage.py seed_team_invitations` replaces it. `entrypoint.sh`'s `web` role runs
it after `migrate`, and for each address in `TEAM_SEED_EMAILS` it issues a panel
invitation carrying the `TEAM_SEED_ROLE` preset — unless that address already
has an account, or already has an invitation whose token has not expired. So a
redeployment sends nothing, and an invitation that expired unaccepted is
reissued rather than stranding its holder.

The list is a **seed, not a recipient list**. Nothing else reads it. Someone who
never accepts is never notified, and enrolling a new colleague afterwards is an
invitation from the panel rather than a code change.

It is a management command rather than `AppConfig.ready()` deliberately:
`ready()` runs in every process that loads Django — all three gunicorn workers,
the Celery worker, beat, and every `manage.py` invocation including `migrate`
itself — so seeding there would send each invitation five times per deployment,
run before `migrate` had prepared the tables, and put a network call in every
process's boot path.

## Bulk email outbox

Queued campaigns are sent by the `process_email_outbox` management command.

**Docker Compose deployments:** delivery is a Celery Beat schedule that fires
`BEAT_OUTBOX_INTERVAL` seconds apart (default 60) and is executed by the
`worker` service. There is nothing extra to configure or run — `docker compose
up` starts it for you. This replaced the old `outbox` service, which was a
`while true; do ... ; sleep 60; done` shell loop.

The claim-token protocol inside the command is unchanged and is what makes
concurrent delivery safe: pending rows are claimed under a per-run token, and
anything still `sending` after `OUTBOX_STALE_CLAIM_MINUTES` is released back to
`pending`. The command remains runnable by hand, which is how you drain the
queue when no worker is running.

**Non-Docker deployments:** run the command every minute via cron, using the
`python` interpreter that this project's dependencies are actually installed
into (e.g. the output of `which python` inside your project's virtualenv —
do NOT hard-code a path from a different environment's virtualenv layout;
there is no virtualenv inside the Docker image, so any such path is wrong
there):

    * * * * * cd /path/to/brandtechsolution && /path/to/your/python manage.py process_email_outbox --verbosity 0 >/dev/null 2>>/var/log/outbox-errors.log

Application DEBUG logging can include credential values, so avoid redirecting full stdout into a persistent log.

Tune `OUTBOX_BATCH_SIZE` (default 50) and the send frequency against your
Mailgun plan's monthly allowance and per-hour rate limit. The old advice here
sized batches around Gmail's ~500/day cap, which is why Mailgun replaced it —
see [Email delivery](#email-delivery).

`OUTBOX_STALE_CLAIM_MINUTES` controls how long a claimed-but-unfinished batch
is held before the reaper releases it back to the queue. A single run's
worst-case duration is bounded by `OUTBOX_BATCH_SIZE × EMAIL_TIMEOUT`
seconds, and this must stay below `OUTBOX_STALE_CLAIM_MINUTES × 60` — this
invariant is enforced by an automated test, so raising the batch size or
timeout requires raising `OUTBOX_STALE_CLAIM_MINUTES` to match.

### Managing campaign recipients

Every campaign card has a **View recipients (N)** button that opens the
recipient list. From there you can search by email or name, add an address
by hand, and remove individual addresses.

What removal does depends on how far the campaign has got:

| Campaign status | Removing a recipient |
|---|---|
| `draft` | Deletes the row and gives the slot back (`total` decreases) |
| `queued` / `sending` / `paused` | Marks the row `skipped`; it is never emailed, and `total` is left alone so the send record stays coherent |
| `sent` / `failed` | Refused — the campaign is finished and its history is immutable |

An address that has already been sent, failed, or is in flight is never
withdrawn, whatever the campaign's status.

**A removal persists across a rebuild.** Removing a recipient records a
durable, per-campaign exclusion for that address, independent of the
recipient row itself (which may be deleted, in the `draft` case). Pressing
**Build recipients** again — for example to add one more manual address, or
after picking up new source records — re-resolves the audience but drops
any address with an active exclusion, so a removed address does not
silently reappear. Manually re-adding that exact address is the one way to
undo this: an explicit add clears the exclusion, so it wins over the
earlier removal and a later rebuild keeps the address.

Adding is allowed for `draft`, `queued`, `sending` and `paused` campaigns —
a new row is simply picked up by the next outbox run. Suppressed
(unsubscribed or bounced) addresses are refused.

### Email validation

Addresses carry a validation status: `unknown`, `valid`, `invalid_syntax` or
`invalid_domain`.

- **Syntax** is checked automatically whenever recipients are built or added.
  It costs nothing and never touches the network.
- **Domains** are checked only when you press **Check domains**, which looks
  up MX records for every recipient. DNS is slow, so this is deliberately a
  button rather than something that happens during Build. Results are cached
  per domain for an hour, so a list of 500 addresses on a handful of domains
  costs a handful of lookups.

**Flagged addresses are still sent to.** The outbox does not skip them —
validation only tells you what looks undeliverable, and **Remove all
invalid** acts on it in one click. Nothing is dropped from a send without
you asking for it.

### Email placeholders

Templates and campaigns support these merge fields in both the subject and body:

| Placeholder | Renders as |
|---|---|
| `{{ name }}` | Recipient's full name (may be blank) |
| `{{ first_name }}` | First word of the recipient's name |
| `{{ email }}` | Recipient's email address |
| `{{ date }}` | Send date, e.g. July 19, 2026 |
| `{{ year }}` | Send year |
| `{{ unsubscribe_url }}` | Per-recipient unsubscribe link (appended automatically if omitted) |

Spacing is flexible — `{{name}}`, `{{ name }}` and `{{  name  }}` all work.
Unknown placeholders render as empty text rather than leaking a literal
`{{ typo }}` into a recipient's inbox; the editor warns about them when you
hit **Preview**, so check that before sending.

The editor stores what you author as `body_source` and derives the
CSS-inlined `body_html` that is actually sent, so editing is lossless and
re-saving never compounds inline styles. The **Source** button exposes the
raw HTML for pasted designs; switching back to the visual editor may
simplify markup Quill does not model. Alignment and indentation are
deliberately absent from the toolbar because email clients discard the CSS
classes Quill uses to implement them.


## Bot protection

Public forms are protected by **Cloudflare Turnstile**. Turnstile rather than
reCAPTCHA because the site already runs behind a Cloudflare Tunnel, so it adds
no new vendor, no new account and no tracking cookie for visitors.

### What is protected

| Endpoint | Why it needs it |
|---|---|
| `POST /appointments/create/` | Creates a booking per request and mails five people. Nothing else bounds it — the unique-email constraint that used to (accidentally) cap repeats was removed in `appointments.0007` |
| `POST /signup/` | Mints real `User` rows on a public URL |
| `POST /api/blogs/<id>/comment/` | Unauthenticated, and the result is shown to every reader |
| `POST /contacts/submit/` | Already had a honeypot and a per-IP rate limit; Turnstile covers the middle ground that clears both |

Blog *likes* are deliberately left alone. A challenge on a like button costs
every real reader something to stop a bot inflating a number nobody makes
decisions on — rate-limit it instead if it becomes a problem.

### How it works

The widget in the page only mints a token. **The check that matters is on the
server**, in `brandtechsolution/turnstile.py`, because a bot never loads the
page — it posts straight to the endpoint. Tokens are single-use and
short-lived, so a harvested one cannot be replayed.

Verification **fails closed**: if Cloudflare cannot be reached the submission
is refused, because "the verifier is down" and "this is a bot" are
indistinguishable from the server's side.

### Setup

Create a Turnstile widget in the Cloudflare dashboard, add the hostnames, then
set both keys:

```bash
TURNSTILE_SITE_KEY=0x4AAA...      # public, rendered into the page
TURNSTILE_SECRET_KEY=0x4AAA...    # secret, only ever sent to siteverify
```

Leaving them unset disables the checks, which is what you want locally — the
widget stops rendering and the server stops verifying, so the two never
disagree. **A Django system check refuses to start with `DEBUG` off and no
secret key**, so a deployment cannot silently lose its bot protection. The
test suite is exempt via `settings.TESTING`; Django's test runner forces
`DEBUG=False`, and without the exemption the guard aborts every test run.

Cloudflare's `api.js` is served from a versionless URL it updates in place, so
there is no stable hash to pin it with `integrity=`.

## llms.txt

`/llms.txt` is a curated index of the site for language models, following the
[llmstxt.org](https://llmstxt.org) convention: a short markdown file naming
the pages worth reading, so an assistant answering questions about Teklora
works from pages we chose rather than whatever fragments a crawler kept.

It is rendered from a template (`brand/templates/brand/llms.txt`) rather than
served as a static file, so every link comes from `{% url %}` and the blog
list is the real one — a hand-maintained copy would rot the first time a route
moved. Only **published** posts are listed; drafts 404 for the public, so
naming one here would be a disclosure by another door.

It is served as `text/plain` so browsers display it rather than downloading
it. The convention names the file `.txt`; its body is markdown either way.

Its "not for indexing" section is **advisory** — it asks politely.
`staff.decorators` and the API permission classes are what actually refuse.

## Staff roles and permissions

Access to the admin panel is controlled by twelve **capabilities**. A
capability is an ordinary Django permission, defined once in
`brandtechsolution/staff/capabilities.py` — that module is the single source
of truth, feeding the permission rows, the `/api/staff/capabilities/` endpoint
and the UI's checkboxes, so the three cannot drift apart.

Capabilities are never granted to a person directly. They are ticked into a
**role** (an `auth.Group`), and people are given roles.

### The capabilities

| Codename | Label | What it gates |
|---|---|---|
| `manage_blog` | Manage blog posts | Creating, editing and deleting blog posts; the panel's unfiltered post list, which is the only place drafts are visible; and reading the AI newsroom at `/editorial/` — its dashboard, article previews, DOCX export and knowledge search |
| `publish_blog` | Publish blog posts | Changing a post's status — both draft → published and published → draft. Creating a post straight into `published` counts as a publish and needs it too. Also every newsroom action that decides what reaches the public site: approving an article (which publishes it), rejecting one, and triggering the pipeline, since it can auto-publish |
| `manage_projects` | Manage projects | Creating, editing and deleting projects |
| `manage_appointments` | Manage appointments | The appointments list and the admin appointment management views |
| `manage_templates` | Manage email templates | Creating, editing and deleting email templates |
| `manage_campaigns` | Create and edit campaigns | Creating and editing campaigns; the default gate for every campaign action not listed below |
| `manage_recipients` | Manage campaign recipients | Building a campaign's audience and adding or removing individual recipients |
| `send_campaigns` | Send campaigns | Queueing, pausing and resuming a campaign — i.e. actually sending |
| `manage_tasks` | Assign and review tasks | Creating, assigning, editing and deleting tasks, and approving or sending back work that has been submitted for review. **Not** needed to see the task board or to do assigned work — see [Tasks](#tasks) |
| `manage_staff` | Manage staff and roles | Everything under **Staff & Groups**: groups, shared mailboxes, people, invitations and the activity log |

Note that `manage_campaigns` and `send_campaigns` are deliberately separate.
Sending is the one irreversible, externally visible action in the panel, so
editing a campaign and pushing it out the door are different permissions.

### Preset roles

Four roles are created by a data migration. They are ordinary groups: rename
them, re-tick their capabilities, delete them, or add your own.

| Role | Capabilities |
|---|---|
| **Editor** | `manage_blog`, `publish_blog`, `manage_projects` |
| **Marketing** | `manage_templates`, `manage_campaigns`, `manage_recipients` |
| **Support** | `manage_appointments` |
| **Administrator** | All twelve |

**Marketing deliberately does not include `send_campaigns`.** Sending is the
irreversible, externally visible action, so it starts reserved to
administrators. There is nothing special about it beyond that: it is an
ordinary capability and can be ticked into any role from the **Roles** tab.
The preset only decides the starting position.

Reversing the migration does not delete these groups. Once created they are
yours — a rollback that dropped them by name would take their memberships and
any customisation with them.

### Groups

A group (Django `auth.Group`; the API still calls it a role, at
`/api/staff/roles/`) holds capabilities, shared mailboxes and members. Under
**Staff & Groups → Groups** you create one, tick what it may do and which
mailboxes it answers, tick the staff who belong to it, and invite new people
into it by email. The preset groups (Editor, Marketing, Support,
Administrator) are ordinary groups and can be edited or deleted.

A `manage_staff` holder who is not a superuser can only grant what they hold:
they cannot add a capability they lack or a mailbox they cannot send from, and
cannot add anyone to (or invite anyone into) a group that grants more than
they hold. They cannot change their own groups or an owner's. Every change is
in the activity log.

### Inviting someone

**Staff & Groups → Invite person**, then an email address and the groups they
should start with. Or open a group under **Groups** and invite addresses
straight into it. The invitee gets a link and sets their own password; no
account exists until they do, and the password they choose must satisfy the
project's configured `AUTH_PASSWORD_VALIDATORS`.

- Links expire after **7 days**. The expiry lives in the signed token itself,
  so it needs no cleanup job. (`STAFF_INVITATION_MAX_AGE`, in seconds,
  overrides the default if you ever need a different window.)
- **Resend** issues a fresh link with a fresh 7-day window.
- **Revoke** deletes the invitation and invalidates its link.
- An invitation is **single-use**. Two people racing the same link produce one
  account, not two.
- If a **staff** account takes the address before the invitation is accepted,
  acceptance is refused with a clear message rather than failing obscurely —
  grant that existing account the roles instead. A resend is refused for the
  same reason, rather than mailing a link that would dead-end.
- **Sign-up accounts.** The login pages no longer link to `/signup/`, but the
  page still exists, and it never checks that the address belongs to whoever
  typed it. Accounts made there start **deactivated** and are not staff. The
  roster lists them for `manage_staff` holders, marked **Not staff yet**
  (`/api/staff/people/?include=signups`), and the people API cannot edit them.
  Opening one offers **Send staff invitation**: a normal invitation to its
  address. Accepting it from that inbox takes the account over: a new password
  (which signs out any existing session), `is_active`, `is_staff`, and the invited roles
  (`took_over_signup` in the `invite_accepted` activity entry). Two accounts
  sharing the address are still refused. See `staff/signups.py`.
- The email is sent directly rather than through the campaign outbox, so it
  never queues behind a bulk send. If delivery fails the invitation row is
  kept so it can be resent, and the failure is written to the audit log.

### What a new account can see

**A staff account with no capabilities sees the dashboard and nothing else.**
That is the expected state for someone just invited and given no roles — not
a bug. Give them a role and the relevant sections appear.

### The rails

Three restrictions keep `manage_staff` safe to delegate.

**You can only grant capabilities you hold yourself.** A non-superuser cannot
hand out a capability they do not have. This applies in all three places a
grant can happen:

1. assigning roles to a person,
2. inviting someone with roles (a grant made before any account exists —
   otherwise you could invite a second address of your own and accept it),
3. adding a capability to a role (otherwise you could tick everything into a
   role you belong to and reload).

**Removing is always allowed.** De-escalation is never restricted, so an
administrator can still strip an account clean even if they do not personally
hold every capability being removed. This is the rail that makes delegating
`manage_staff` safe: a delegate can administer everyone else, but cannot
bootstrap themselves upward.

**Superuser accounts are protected.** A non-superuser holding `manage_staff`
cannot change a superuser's roles or active state — otherwise a delegate could
lock the owner out of their own site.

**You cannot lock yourself out.** A non-superuser cannot edit their own roles
or deactivate their own account. One flat rule, rather than
last-admin-standing arithmetic.

Superusers bypass every capability check (Django's `has_perm()` returns `True`
for them unconditionally) and are exempt from all three rails above. They are
the escape hatch, and can manage each other and themselves freely.

### Notes for maintainers

**`is_staff` is a required floor, in addition to any capability.** The site has
a public `/signup/` page that creates ordinary non-staff users, so a
capability alone is not enough: an account without `is_staff` is refused even
if it somehow holds the permission. Every enforcement path checks both.

**Nav gating is cosmetic.** The panel template hides sections a user cannot
use, and exposes the held set to JavaScript as `window.CAPABILITIES`. That is
a convenience, not the security boundary — every API enforces its own
capability independently on every request. Do not read the template's `{% if
can.x %}` blocks as enforcement.

Enforcement is spelled the way each layer wants it, but always means the same
thing:

- DRF views use `has_capability("codename")` from `staff/permissions.py`.
- Plain Django views use the `@capability_required("codename")` decorator from
  `staff/decorators.py`.
- The hand-rolled JSON views in `brand/api_views.py` call
  `capability_required_json(request, "codename")`.

### The audit log

Role and account changes are recorded in an **append-only** log, visible under
**Staff & Roles → Activity**. There is no update or delete route on it by
construction. Each entry's summary is rendered at write time, so it still
reads correctly after the user or role it names has been deleted.

Recorded: invitations sent, resent, failed to send, revoked and accepted; role
assignments changed; accounts deactivated and reactivated; roles created,
updated and deleted.

### Blog drafts

Blog posts are now created as **drafts** and need `publish_blog` to go live.
The public blog list and post pages show published posts only; a draft 404s
for the public. Someone with `manage_blog` but not `publish_blog` can write
and edit freely but cannot change a post's status in either direction.

## Tasks

**Tasks** is where work is handed out and signed off. It is the one panel
section every staff account can open, capability or not.

### Who sees what

| | No capability | `manage_tasks` |
|---|---|---|
| See the whole board and who is on what | ✅ | ✅ |
| Comment on any task | ✅ | ✅ |
| Mark **your own** part done | ✅ | ✅ |
| Create, assign, edit, delete | ❌ | ✅ |
| Approve or send back | ❌ | ✅ |

Reading is deliberately open. The board's value is that everyone can see what
the team is carrying, so hiding it behind a capability would mean granting
that capability to everybody — and with it the right to assign work.

### The status ladder

```
        assignees tick off their own part
OPEN ──────────────────────────────────────► IN REVIEW ──────────► DONE
  ▲            (all of them, not just one)                approve
  │
  └──────────────────────────────────────────────────────────┘
                    send back, with a reason
```

**Staff cannot reach DONE.** They mark their own share complete; the task
moves itself to *In review* once every assignee has done so, and only a
`manage_tasks` holder approves it. If people could close their own work there
would be nothing left to review.

Some consequences worth knowing:

- **Completion is per person.** With three people on a task, one finishing
  says nothing about whether the task is finished. The board shows
  "2 of 3 done".
- **Un-ticking pulls a task back out of review.** If someone decides they
  are not done after all, the task returns to *Open*.
- **Sending back clears every completion**, not just the submission. The work
  is going back to the whole group, so leaving people ticked off would bounce
  it straight into review again on the next save.
- **A reason is required to send back.** The people redoing the work need to
  be told what was wrong with it. It lands in the task's timeline.
- **An unassigned task never submits itself.** "Every assignee is finished" is
  vacuously true of nobody.
- **Status is not writable through the API.** `PATCH {"status": "done"}` is
  ignored — the ladder is only walked by the `complete`, `approve` and
  `reopen` actions, each of which enforces its own rule. Otherwise a task
  could read *Done* while its assignments were still outstanding.

### Being told about it

Two channels, both pointing at the same underlying state:

- **In panel** — a badge on the Tasks nav item. Reviewers see the count of
  tasks waiting on their approval; everyone else sees their own outstanding
  work.
- **Email** — everyone holding `manage_tasks` is mailed when a task enters
  review. Delivery failure is logged and swallowed: the review queue is the
  real signal, and a mail server problem must not roll back a submission a
  staff member legitimately made.

### API

Mounted at `/api/work/`. Every endpoint needs a staff account.

| Endpoint | Method | Gate |
|---|---|---|
| `/api/work/tasks/` | GET | any staff |
| `/api/work/tasks/` | POST | `manage_tasks` |
| `/api/work/tasks/{id}/` | PATCH, DELETE | `manage_tasks` |
| `/api/work/tasks/{id}/complete/` | POST | own assignment, or `manage_tasks` for anyone's |
| `/api/work/tasks/{id}/uncomplete/` | POST | own assignment, or `manage_tasks` |
| `/api/work/tasks/{id}/approve/` | POST | `manage_tasks` |
| `/api/work/tasks/{id}/reopen/` | POST | `manage_tasks`, `reason` required |
| `/api/work/tasks/{id}/activity/` | GET, POST | any staff |
| `/api/work/summary/` | GET | any staff (`needs_review` reads 0 without `manage_tasks`) |
| `/api/work/assignable/` | GET | any staff |

List filters: `?mine=1`, `?active=1` (everything not yet approved),
`?status=open|in_review|done`, `?assignee=<id>`, `?q=<search>`.

Only `is_staff`, active accounts can be assigned work — `/signup/` is public,
so `User` at large includes customers, and assigning one a task would put it
in a dashboard they cannot open.

### Upgrading an existing deployment

```bash
python manage.py migrate
```

`staff.0007` grants `manage_tasks` to the **Administrator** preset, so
existing administrators can use the section immediately. Editor, Marketing
and Support are left alone — assigning work is not part of any of them, so
tick it in from **Staff & Groups → Groups** if you want it there. Reversing the
migration removes that one grant and leaves the group and every hand-made
grant intact.

---

## Saved GitHub data and background updates

GitHub Manager reads repository metadata, account details, README previews, commit lists and document checks from persistent database snapshots. Opening or reloading a screen does **not** call GitHub directly. Empty commit lists and missing READMEs are saved too, so they do not become repeated cache misses. Local project titles and descriptions remain editable and appear immediately without a GitHub refresh.

| Data | Refresh behavior |
|---|---|
| Repository discovery and metadata | Due after one hour; the scheduled GitHub job or a stale page queues an update. |
| Account and organisation details | Reused for six hours. |
| README, commit lists and document checks | Reused for unchanged repository revisions for up to six hours; changed push timestamps/default branches trigger refresh. |
| CHANGELOG/ROADMAP text | Persisted once and shared with task imports; unchanged file hashes reuse saved text after a code push. |

The existing worker and Beat perform updates. Verified default-branch push webhooks invalidate only the affected repository. Task polling checks metadata at `BEAT_TASK_REPO_INTERVAL`, but skips commit/document/roadmap downloads for revisions it has already processed. Commit summaries avoid one additional stats request per commit. Metadata discovery also reuses the same repository objects when updating tracked projects.

The **Refresh** button requests background work and leaves saved data visible, with an update timestamp and status. Concurrent requests share a database refresh lease. Failures keep the last successful data; rate-limit responses delay further work until the retry/reset window. Cache entries are scoped to a one-way hash of the configured GitHub credential/account, so changing credentials cannot expose the previous account’s private repository list. No credentials are stored in these cache records.

Cold snapshots may show a preparation message until the worker finishes. Docker Compose already starts the worker and Beat and applies the new database migrations with `docker compose up --build -d`; no cache-flush command or new environment variables are required. The public commits GET endpoint ignores `?refresh=1`; manual updates use the `manage_projects`-protected `POST /api/github/refresh/` endpoint.

See the [cache specification](docs/specs/2026-10-28-github-database-cache-spec.md) and [execution plan](docs/plans/2026-10-28-github-database-cache-plan.md).

## GitHub roadmaps, documentation and the task backlog

**Admin → Tasks** has two workspaces:

- **Team tasks**: assigned work, personal tasks, reviews and approved work.
- **Project backlog**: open roadmap items and documentation repairs awaiting an owner, with project filtering, search and an **Assign** action. Task managers can select one or more active staff. Assigned items leave the backlog and appear on the team board.

The source is the projects already synced in **GitHub Manager**. No repository names need to be entered again on the Tasks page. A successful project sync queues its task import, and Celery Beat discovers existing GitHub-synced projects and checks their roadmaps every `BEAT_TASK_REPO_INTERVAL` seconds (default `600`). `GITHUB_ACCESS_TOKEN` must be able to read these repositories. Importing never assigns people automatically or changes existing assignments. Future authenticated automation can use the same capability-protected assignment endpoint, `POST /api/work/tasks/<id>/assign/`, with `{"assignee_ids": [1, 2]}`; no AI assignment policy is enabled.

Imports read `ROADMAP.md`, then `docs/ROADMAP.md`. Each unchecked leaf checkbox in an unfinished milestone becomes an unassigned task. Matching unlinked manual tasks are reused and imports are idempotent. Checked items without assignees leave the available backlog without being approved. Project titles and milestone context help managers choose work before assigning it. The refresh button reloads the imported list; it does not initiate GitHub imports.

The same document audit shown in GitHub Manager checks **README.md, CHANGELOG.md, ROADMAP.md and LICENSE**. Missing files and format/quality findings create one unassigned **Documentation** repair task per affected document, containing its current problems and fix instructions. A missing roadmap does not block these tasks. Repeated checks update existing work rather than creating duplicates or changing assignees. Unknown/failed audits do not claim that files are missing or resolved.

When a document passes its checks, an unassigned repair leaves the backlog; an assigned repair moves to **In Review**. Approval is always manual. A recurring problem reuses unapproved work or creates a new repair task if the earlier one was already approved. Default-branch pushes changing any required document queue a recheck when the webhook is configured; polling remains the fallback.

Reference work in commits as `Task #42`. A default-branch commit saying `Closes Task #42` (also fixes, resolves, completes or done), or a merge of a branch such as `feat/task-42-title`, completes outstanding assignments and submits the task to **In Review**. Only a task manager can approve it to **Done**. Checking a roadmap item also submits already assigned work. After rejection, an unchanged checked item will not repeatedly resubmit work. Submit again through the board, a new closing commit, or by unticking and later reticking the roadmap item. Feature-branch pushes link commits without submitting work when the optional webhook is configured. Polling initially reads the past seven days of default-branch commits; repeated deliveries retain one entry per task.

Docker deployment runs migrations and collects static files through the web entrypoint, and starts the worker and Beat:

```bash
docker compose up --build -d
```

An optional GitHub push webhook can target `https://<your-host>/api/work/github/webhook/`. Choose JSON content, push events, and a secret matching `GITHUB_WEBHOOK_SECRET` in the application environment. Without a secret, polling still works. The worker and Beat must run for ongoing automatic imports; a standalone development web server only displays previously imported data.

See the [backlog specification](docs/specs/2026-10-28-roadmap-backlog-spec.md) and [execution plan](docs/plans/2026-10-28-roadmap-backlog-plan.md).

## 🛠️ Development Workflow & Repository Standards

Teklora operates under a **file-based single source of truth** engineering workflow tightly coupled with our internal platform task system:

- 📖 **[CONTRIBUTING.md](file:///home/bigaddict/Projects/Codebases/brantech-full-website/CONTRIBUTING.md)**: Developer workflow guide, branch conventions, and definition of done.
- 📋 **[CHANGELOG.md](file:///home/bigaddict/Projects/Codebases/brantech-full-website/CHANGELOG.md)**: Semantic change history; updated on every pull request.
- 🗺️ **[docs/ROADMAP.md](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/ROADMAP.md)**: Active milestones, upcoming initiatives, and platform capabilities.
- 🤖 **[AGENTS.md](file:///home/bigaddict/Projects/Codebases/brantech-full-website/AGENTS.md)**: Canonical rules for AI coding assistants (symlinked to `.cursorrules`, `CLAUDE.md`, `GEMINI.md`, etc.).

---

## 📝 License & Contact

This repository is proprietary software for **Teklora Solutions Ltd**.

- **Email**: [teklorasolutionsltd@gmail.com](mailto:teklorasolutionsltd@gmail.com)
- **Phone**: +254 704 894220
- **Status**: ✅ Production Ready
