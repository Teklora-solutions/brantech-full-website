# Knowledge Library UI redesign execution — Tasks #35 / #40

1. Inspect shared admin theme and library behavior; preserve existing authentication, ACLs, processing/public approvals and current-version submission checks.
2. Implement theme-token-based, feature-scoped CSS and reusable template components for navigation, fields, document rows, badges and pagination.
3. Redesign browsing/review queues, upload, detail/sharing and administrator workflows; add progressive enhancement for file selection/upload progress.
4. Add permission-filtered summaries/status filtering and view context; test counts, empty/search states, badge labels, accessibility markup and existing POST behavior.
5. Launch a disposable local PostgreSQL database and authenticated fixture server; use available cached Playwright/Chromium for desktop/mobile/light/dark screenshots and interaction checks. No production writes or provider calls.
6. Run automated affected-app tests, review screenshots and correct layout defects. Update README, changelog and roadmap with actual results.

## Delivery and verification

Implemented shared-theme, scoped CSS/JS and reusable field/pagination components; replaced all four library templates. Added human-readable state/activity labels, permission-filtered summaries and status/search filtering, distinct empty states, unique field IDs and active sidebar navigation. Review-queue links target the relevant review panel, with sticky-header-safe scroll spacing. Backend authorization, state transitions, storage, jobs and the always-available policy are unchanged; no migrations are needed.

### Automated checks

- **927 tests passed** across `knowledge_base ai_workflows staff tasks` on isolated PostgreSQL 16/pgvector with stub providers, tracing disabled via context and a temporary fast MD5 test password hasher. Production password settings are unchanged.
- **59 library tests passed** separately with the normal project test settings/password hasher. New coverage checks permission-scoped/deduplicated counts, filters, empty/search/review states, pagination, static assets and unique accessible form IDs.
- An expanded run including `brand` ran **1,271 tests** and exposed **37 existing failures/errors** in older brand tests. A detached, unchanged `f467fcd` worktree reproduced the **same 37 failing cases** across its 344 brand tests, with no new failing cases from this redesign. Those unrelated failures were not altered here.
- Django system checks, migration-drift check, JavaScript syntax check and `git diff --check` passed.

### Real-browser acceptance

Used cached Playwright/Chromium against an authenticated fixture-only server and disposable local database; no production records or real providers were used.

- Captured and inspected desktop (1440px) and mobile (390px), light/dark screenshots of empty and populated libraries, upload and document detail screens; also captured processing/public review and sharing panels.
- Verified no horizontal document overflow or duplicate DOM IDs on tested pages, no JavaScript page errors, and keyboard focus movement from search to the status filter.
- Exercised search/no-result/reset, processing filtering, drag/drop selection, rejected file extensions, successful private XHR upload/redirect, malformed-PDF server rejection with form preservation, connection-failure recovery, sharing POST and public-approval POST. No external processing clearance was submitted to a real provider.
- Browser review caught and fixed search-icon/text overlap and sticky-header clipping of anchored sharing panels. Final snapshots include `/tmp/teklora-library-empty-desktop-dark.png`, `/tmp/teklora-library-documents-desktop-dark.png`, `/tmp/teklora-library-upload-desktop-light.png`, `/tmp/teklora-library-documents-mobile-dark.png`, and focused sharing/review screenshots. These are local verification artifacts, not production screenshots.

No merge, push or production deployment is assumed by this redesign request. Actual OCR execution, deployment backup verification and security/operational acceptance remain separate work.
