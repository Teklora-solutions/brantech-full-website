# Staff knowledge library completion — Tasks #34, #35, #40

## Scope and execution

Complete the approved document-library specification in this checkout. No EduShare changes, production migration/deployment, task reassignment, or task-board approval is implied.

1. Persist documents, immutable versions, grants, per-version review decisions, chunks and privacy-safe audit events. Originals use private filesystem storage outside public media.
2. Provide a single policy-backed queryset and locked mutation service. Tighten the existing administrator check and exclude protected scopes from every generic recall, including explicitly scoped calls. Current-version and readiness predicates apply before retrieval ranking.
3. Add bounded format validation and asynchronous extraction/OCR/embedding on `library_processing`. Use local PDF/DOCX extraction and local Tesseract OCR (PDF rasterisation via pdftoppm), with no external OCR provider. External embeddings are pinned to the approved Gemini embedding space; fail closed on provider mismatch. Retry transient failures with bounded attempts, recover stale jobs, and purge deleted content daily.
4. Add staff Django pages under `/library/`: search/list/upload, details/text/download, replacement and metadata editing, sharing, separate clearance/public review queues and actions. Link from the existing panel navigation. All mutations are CSRF-protected POSTs, stale version submissions fail, and all responses are private/no-store.
5. Add regression tests for permissions, upload validation, state transitions, retrieval isolation, worker failures/races and purge. Update README, changelog and roadmap with actual results, not inferred completion.

## Interface and operational decisions

- Operator follow-up: remove the library feature toggle entirely. Pages, navigation, ingestion jobs and public-approved library tools are always available under existing authentication, ACL and administrator review rules. Remove the configuration field, setting, environment example and redundant context processor; test availability without any opt-in configuration.
- `LIBRARY_STORAGE_ROOT` must be outside MEDIA_ROOT/STATIC_ROOT. Files use random keys and attachment-only authenticated streaming.
- Uploads: 25 MiB, PDF/DOCX/TXT/MD/PNG/JPEG; at most 30 PDF pages, 10 MiB extracted text, 500 chunks, bounded DOCX expansion. No HTML rendering of extracted content.
- Clearance records classification, provider, reviewer, time and reason; restricted data cannot be approved. Local OCR has no provider egress. Embeddings must match the exact cleared provider and active space, with checks before each call and before persistence.
- Replacement and metadata edits revoke public eligibility. Every mutation locks the parent document; worker output is staged in memory and committed only after checking current version, clearance and deletion again.
- Public retrieval is a server-owned service, never a caller-selected audience/actor on an HTTP endpoint. AI integration uses a tool factory closed over trusted request context; generic chat memory cannot retrieve library records.
- Celery dedicated prefork worker concurrency 2, soft timeout 55s/hard timeout 60s. Document parser subprocesses have explicit timeouts. Beat recovers abandoned jobs and purges within the 30-day live deletion deadline. Production backups and user acceptance remain release checks; repository prose is not proof of operational backup retention.

## Checkout delivery record — 2026-11-12

- Implemented models/migrations `0005` and `0006`, private storage, locked mutation services, bounded asynchronous worker, local extraction/OCR adapters, semantic/lexical retrieval, privacy maintenance, staff pages/forms and panel navigation.
- Added public-only library tools to assistant/newsroom suites. Internal tool construction remains server-actor-bound and is deliberately not attached to public chat. Generic recall AND generic reembedding exclude protected library scopes; crafted generic backfill plans fail before provider invocation.
- Strengthened administrator role/capability checks; generation tokens invalidate work from earlier clearance decisions. Worker output is staged outside the database and committed only against current, cleared, non-deleted state. Embedding tracing is explicitly disabled.
- Added tags, upload-authority acknowledgement, independent processing/public badges, accessible native forms/details, no-store responses, attachment-only downloads, explicit safe errors and append-only review/access history.
- Added Docker OCR packages and a dedicated resource-bounded queue worker; default maintenance worker now shares private storage. Beat purges deleted rows/files/vectors, cleans orphaned originals, and marks interrupted processing as retryable failure.
- Corrected two existing staff regression assertions that predated the already-migrated library/developer capabilities; no capability grants or live assignments changed.

### Verification results

- Affected-app suite: **921 tests passed** (`knowledge_base ai_workflows staff tasks`) on a disposable local PostgreSQL 16/pgvector container, using stub model providers, disabled tracing context and a temporary fast MD5 test password hasher. Production password-hashing settings were not changed.
- Default-runner library suite: **53 tests passed** separately with normal project password-hashing settings.
- Operator follow-up verification after removing the toggle: **921 affected-app tests passed** again on isolated PostgreSQL/pgvector with the temporary fast test hasher and stub providers. Availability/navigation regression now runs without any feature-setting override; public AI suite expectations include the always-registered public-library tool.
- Applied all migrations on the disposable database, rolled knowledge_base back to `0004`, and reapplied `0005`/`0006`: passed. `makemigrations --check --dry-run`: no changes. `manage.py check`: no issues.
- `git diff --check`, `bash -n entrypoint.sh`, and `docker compose config --no-env-resolution --quiet`: passed. Compose interpolation warns if deployment database variables are absent; no real services were launched by this config check.
- Initial delivery did not claim actual OCR binary execution or browser acceptance. The subsequent [UI redesign](2026-11-12-library-ui-redesign-plan.md) located cached Playwright/Chromium and completed local desktop/mobile/light/dark and keyboard/browser-flow checks. Tesseract execution remains unverified; parser/DOCX/PDF/scan paths and worker/HTTP workflows use generated documents and stub OCR/embedding dependencies.

### Outstanding release gates (not implementation/task-board completion)

- Build/run the updated Docker image and dedicated worker with Tesseract/Poppler, then smoke-test real PDF scans and PNG/JPEG OCR; confirm queue timeout/memory limits in the deployment.
- Local mobile/desktop/keyboard browser acceptance of upload, sharing and public review is now covered by the UI redesign execution record; repeat the smoke checks against the deployment configuration.
- Verify shared private storage/permissions, real provider approval/credentials/space, backup retention/expiry and restore/redeletion procedure.
- Obtain security/operational acceptance as part of deployment. No library feature toggle exists. No production migrations/deployment, real-document provider calls or live task-board approvals have been performed.

## Verification / release

Use an isolated PostgreSQL/pgvector test database and fake embedders; never tests against production. Run `manage.py test knowledge_base ai_workflows staff tasks`, migration drift checks and Django checks. Verify security/operational behavior and run a browser smoke test during deployment; the library does not require opt-in configuration. Report unavailable infrastructure or dependencies explicitly.
