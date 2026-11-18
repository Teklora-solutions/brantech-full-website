# 🏛️ Teklora Solutions Fullstack Platform

> **Internal Enterprise Engineering & AI Technology Platform**  
> Single source of truth for repository architecture, service runtime orchestration, local development, and core subsystems.

---

## 🏗️ Architecture & Service Topology

Teklora runs as a containerized multi-tier Django platform behind a Cloudflare Zero Trust tunnel with isolated workers and background sidecars:

| Service | Technology / Image | Role & Responsibilities | Port / Route |
|---|---|---|---|
| **`web`** | Python 3.13 / Gunicorn / WhiteNoise | Main Django application server (3 workers, 120s timeout) | Internal `8000` (proxied by tunnel) |
| **`db`** | `pgvector/pgvector:pg16` | Relational database + vector embeddings (`pgvector`) | Internal `5432` |
| **`redis`** | `redis:7-alpine` | Broker (db 0), Celery results (db 1), Django cache (db 2) | Internal `6379` |
| **`worker`** | Celery (prefork pool) | Background tasks: newsroom editorial, campaign outbox, GitHub sync | Shared queue |
| **`library-worker`** | Celery (`library_processing`) | Bounded OCR (Tesseract/Poppler) & embedding workers | `library_processing` queue |
| **`beat`** | Celery Beat | Scheduled recurring jobs (single replica by design) | Cron / Periodic tasks |
| **`document-preview`** | `gotenberg/gotenberg:9.5.0` | Sandboxed DOCX → PDF converter sidecar (LibreOffice engine) | Internal `preview-internal` network |
| **`cloudflared`** | `cloudflare/cloudflared` | Secure outbound edge tunnel; eliminates exposed host ports | Inbound ingress |

---

## ⚡ Developer Runbook ("How to Run")

### Option A: Complete Stack via Docker Compose (Recommended)

This spins up all 8 services (PostgreSQL, Redis, Web, Workers, Beat, Gotenberg sidecar, and Tunnel):

```bash
# 1. Ensure .env and cloudflared.env are configured at repository root
cp brandtechsolution/env.example .env
cp cloudflared.env.example cloudflared.env  # or create cloudflared.env with TUNNEL_TOKEN=...

# 2. Build and launch all services in background
docker compose up -d --build

# 3. Inspect container logs
docker compose logs -f web
docker compose logs -f worker library-worker

# 4. Run one-off management commands
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py init_vector_stores
```

### Option B: Local Python Development (Bare-Metal / Virtualenv)

For rapid iteration on Django models, views, or unit tests:

```bash
# 1. Prerequisites: Python 3.12+, Tesseract OCR, Poppler utils, Redis (or set eager Celery)
cd brandtechsolution
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 2. Local environment configuration
cp env.example .env
# Edit .env to set:
#   DATABASE_ENGINE=sqlite3 (for lightweight dev) or PostgreSQL
#   CELERY_TASK_ALWAYS_EAGER=true (to run tasks inline without Redis)

# 3. Database migrations & initial data
python manage.py migrate
python manage.py seed_team_invitations
python manage.py runserver 127.0.0.1:8000
```

> **Running local Celery workers (outside Docker):**  
> If testing asynchronous background queues locally, run:  
> `celery -A brandtechsolution worker -l info` (General worker)  
> `celery -A brandtechsolution worker -Q library_processing --concurrency=2 -l info` (Library OCR worker)  
> `celery -A brandtechsolution beat -l info` (Periodic scheduler)

---

## 📂 Repository Layout

```
.
├── brandtechsolution/            # Django project root
│   ├── brand/                    # Core website, marketing views, models (Projects, Career, SiteContent)
│   ├── staff/                    # RBAC engine (18 capabilities, groups, handles, API keys)
│   ├── tasks/                    # Task lifecycle, multi-assignee board, deliverables, GitHub automation
│   ├── knowledge_base/           # Semantic memory, document library, embedding lifecycle & spaces
│   ├── editorial/                # Newsroom multi-agent pipeline (models, services, pipeline orchestrator)
│   ├── ai_workflows/             # Unified AI model harness, dynamic touchpoints registry, Gemini/Vertex adapters
│   ├── messaging/                # Mailbox management, Mailgun HTTP backend, campaign outbox, autoreply
│   ├── appointments/             # Virtual strategy consultation booking & availability checking
│   └── scripts/                  # Standalone tools (teklora_mcp.py, seeders)
├── docs/                         # Canonical technical specifications and architecture plans
│   ├── specs/                    # Formal technical specifications and ACL contracts
│   ├── plans/                    # Phased execution and delivery plans
│   └── ROADMAP.md                # Platform milestone tracker
├── skills/                       # AI Agent skills (teklora-developer canonical skill)
├── docker-compose.yml            # Multi-service production/staging orchestration
├── Dockerfile                    # Python 3.13 image with Tesseract & Poppler dependencies
├── entrypoint.sh                 # Multi-role service dispatcher (web, worker, library-worker, beat)
├── CHANGELOG.md                  # Keep-a-Changelog compliance ledger
└── LICENSE                       # Canonical Teklora Solutions proprietary license
```

---

## 🧩 Core Platform Systems

### 1. Unified AI Harness & Touchpoints Studio (`/admin-panel/?section=ai`)
- **Multi-Provider Harness**: Centralized model execution across Google Gemini, Google Cloud Vertex AI, Anthropic, OpenAI, DeepSeek, OpenRouter, and Codex/ChatGPT device code login.
- **Dynamic Touchpoints Pattern**: Any LLM invocation point in the application registers via `@register_touchpoint(name, description, default_provider, default_model)`. Operators can dynamically switch providers, tune temperatures, or reassign models in Django admin without code changes.
- **Token Accounting & Budgets**: Persistent per-token cost tracking and pricing catalogue (`pricing.toml`).
- **Docs**: [AI Workflows Architecture](file:///home/bigaddict/Projects/Codebases/brantech-full-website/brandtechsolution/ai_workflows/README.md) • [Touchpoint Registry Plan](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/plans/2026-10-30-ai-configuration-and-touchpoint-registry.md).

### 2. Staff Knowledge Library & In-Browser Readers (`/library/`)
- **Private Document Management**: Deny-by-default access control covering PDF, DOCX, TXT, Markdown, and image scans (up to 25 MB). Enforces strict owner/group/organisation ACLs.
- **In-Browser Document Reader**: Native PDF/image preview, escaped text reader, and sandboxed DOCX-to-PDF sidecar conversion via Gotenberg. No external provider is ever called for rendering.
- **Managed Embedding Lifecycle**: Admin-controlled embedding migrations (`/library/embeddings/`) between Gemini Embedding 001 and 2 (Vertex vs Developer API) with durable checkpoints, recovery workers, and validated rollback.
- **Docs**: [Library Specification](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/specs/2026-11-04-document-library-spec.md) • [ACL & Retrieval Contract](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/specs/2026-11-07-library-acl-and-retrieval-contract.md) • [Embedding Lifecycle Spec](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/specs/2026-11-13-embedding-lifecycle-spec.md).

### 3. Task Management & Deliverables Engine (`/admin-panel/?section=tasks`)
- **Status Ladder**: `Open` $\rightarrow$ `In Review` $\rightarrow$ `Done`. Individual assignees mark their part complete; task moves to `In Review` once all assignees complete. Only `manage_tasks` holders approve to `Done`.
- **Document-Backed Deliverables**: Assignment-specific submission rounds backed by Knowledge Library documents. Supports `Standard`, `Document`, `Code`, or `Document or code` requirements.
- **GitHub Task Automation**: Automatic commit linking via `Task #42` syntax, automatic review submission on default-branch merge/closing commits, and roadmap import backlog.
- **Docs**: [Deliverables Spec](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/specs/2026-11-12-task-document-deliverables-spec.md) • [GitHub Task Automation Spec](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/specs/2026-10-28-github-task-automation-spec.md).

### 4. Developer Portal & Coding Agent MCP (`/admin-panel/?section=developer`)
- **Developer API Keys**: Personal cryptographic keys (`tkl_live_...`) with SHA-256 hashing and DRF `DeveloperApiKeyAuthentication` support.
- **Zero-Dependency Teklora MCP Server**: Standalone Model Context Protocol stdio server (`brandtechsolution/scripts/teklora_mcp.py`) exposing task management, developer profiles, repositories, and semantic search to coding agents.
- **Agent Auto-Setup**: Canonical `/developer/setup/` endpoint serving tailored instructions for Claude Code, Cursor, Windsurf, Cline, and Google Antigravity.
- **Docs**: [Developer Skill & MCP Plan](file:///home/bigaddict/Projects/Codebases/brantech-full-website/docs/plans/2026-11-07-developer-skill-mcp-and-keys-plan.md).

### 5. Staff Capabilities & Access Control (RBAC)
- **18 Fine-Grained Capabilities**: Structured across 4 functional groups in `staff/capabilities.py`:
  - **Content**: `manage_blog`, `publish_blog`, `manage_projects`, `manage_appointments`
  - **Communications**: `view_inbox`, `handle_inquiries`, `view_all_mail`, `receive_inquiry_emails`, `manage_mail_limits`, `manage_templates`, `manage_campaigns`, `manage_recipients`, `send_campaigns`
  - **Administration**: `manage_tasks`, `manage_staff`, `receive_alerts`, `approve_library_publication`
  - **Developer Tools**: `generate_api_keys`
- **Preset Roles**: `Administrator` (all 18), `Editor`, `Marketing`, `Support`.
- **Custom Staff Groups & Shared Mailboxes**: Link staff accounts to shared mailboxes (info@, careers@, hr@, etc.) and specific capabilities.

### 6. Public Portal, CSR Initiatives & Careers (`/partnerships/` & `/careers/`)
- **Dynamic Careers Portal**: Live database querying of `Career` models, prefilled application mailto links (`JOB-<id>`), and automated SPF-validated applications-closed auto-responder (`messaging/autoreply.py`).
- **CSR Mandate**: Formal social impact initiatives for vulnerable children and Gospel ministries, plus the EduShare Zero-Rating Alliance.
- **Partnerships Management**: Themed admin dashboard (`/admin-panel/partnerships/`) with instant Close / Reopen controls.

---

## 🔌 Core API Endpoints

| Area | Method & Route | Access Gate | Description |
|---|---|---|---|
| **Tasks** | `GET /api/work/tasks/` | Any staff | List active and assigned tasks (`?mine=1`, `?q=...`) |
| | `POST /api/work/tasks/` | `manage_tasks` | Create new platform task with delivery requirements |
| | `POST /api/work/tasks/<id>/deliverables/rounds/` | Assigned staff | Submit document deliverables from Knowledge Library |
| | `POST /api/work/tasks/<id>/complete/` | Assignee / `manage_tasks` | Mark assignment complete (triggers In Review when all finish) |
| | `POST /api/work/tasks/<id>/approve/` | `manage_tasks` | Transition task from In Review to Done |
| **Developer** | `GET /developer/setup/` | Public / Developer | Machine-readable agent setup instructions |
| | `POST /api/staff/developer/keys/` | `generate_api_keys` | Issue new personal developer API key |
| **Library** | `GET /api/library/documents/` | Any staff | ACL-filtered library document search |
| | `GET /library/previews/<id>/` | Permitted staff | In-browser preview (PDF, DOCX, image, safe text) |
| **Projects** | `POST /api/projects/<pk>/sync-github/` | `manage_projects` | 1-click on-demand GitHub sync for a project |
| **Messaging** | `POST /api/messaging/mail/threads/<id>/forward/` | Permitted sender | Forward email thread with selected attachments |
| **Appointments** | `POST /appointments/check-availability/` | Public | Real-time calendar slot validation |

---

## 🧪 Testing & Verification Standards

Always execute automated tests for affected apps prior to pushing or declaring tasks complete:

```bash
# Run all project test suites
python manage.py test

# Test core enterprise apps
python manage.py test staff tasks knowledge_base ai_workflows editorial

# Test messaging, campaigns, and appointment workflows
python manage.py test messaging appointments brand
```

---

## ⚙️ Environment Variables Reference

Key configuration settings from `brandtechsolution/env.example`:

| Variable | Default / Format | Description |
|---|---|---|
| `DEBUG` | `False` in prod | Django debug mode (system checks refuse production without bot protection) |
| `SECRET_KEY` | string | Cryptographic signing key |
| `ALLOWED_HOSTS` | `["localhost"]` | Allowed HTTP Host headers |
| `DATABASE_HOST` | `db` (Docker) / `localhost` | PostgreSQL host |
| `REDIS_HOST` | `redis` (Docker) / `localhost` | Redis broker and cache host |
| `MAILGUN_API_KEY` | `key-...` | Outbound email delivery key |
| `MAILGUN_DOMAIN` | e.g. `mg.teklora.co.ke` | Verified sending domain |
| `GOOGLE_API_KEY` | string | Google Gemini API key |
| `GOOGLE_APPLICATION_CREDENTIALS` | `./credentials/vertex-sa.json` | Google Cloud Service Account for Vertex AI |
| `TURNSTILE_SECRET_KEY` | `0x4AAA...` | Cloudflare Turnstile secret key for bot protection |
| `GITHUB_ACCESS_TOKEN` | `ghp_...` | GitHub API token for repository synchronization |

---

## 📋 The "Every Update" Engineering Contract

Every engineer and AI agent working on this codebase must adhere to the maintenance obligations in [GEMINI.md](file:///home/bigaddict/Projects/Codebases/brantech-full-website/GEMINI.md):
1. **`CHANGELOG.md`**: Add an entry under `## [Unreleased]` for every feature, fix, or change.
2. **`docs/ROADMAP.md`**: Keep milestone tasks and progress updated.
3. **`README.md`**: Update when user-facing features, architecture components, or environment configurations change.
4. **`docs/specs/` & `docs/plans/`**: Create specifications and execution plans for all non-trivial features.

---

## 📝 License & Contact

This repository and its codebase are proprietary intellectual property of **Teklora Solutions Ltd**.  
See [LICENSE](file:///home/bigaddict/Projects/Codebases/brantech-full-website/LICENSE) for canonical terms.

- **Official Email**: `teklorasolutionsltd@gmail.com`
- **Phone**: `+254 704 894220`
- **Location**: Nairobi, Kenya
- **Status**: ✅ Production Ready
