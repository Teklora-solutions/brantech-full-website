# Library browser previews execution plan

Status: Implemented and verified locally; release pending. User selected native PDF/image/text previews and additionally requested DOCX → PDF.

- [x] Inspect library access policy, current extracted-text-only UI, private storage and purge lifecycle.
- [x] Define private version-scoped preview and isolated DOCX conversion contract before implementation.
- [x] Add bounded private conversion/cache service, preview endpoint, purge integration and deployment settings.
- [x] Add inline PDF/image/text reader, explicit preparation/failure/fallback UI and original download controls; retain extracted text separately. Narrow screens use Read PDF in its own browser tab.
- [x] Add regression tests and run knowledge_base/tasks/staff/ai_workflows/admin-access tests plus system/Compose checks.
- [x] Verify actual synthetic DOCX conversion and browser desktop/mobile light/dark views with isolated fixtures.
- [x] Record results and update CHANGELOG, README and ROADMAP. Do not commit/push/deploy without user authorization.

Specification: [Private browser previews](../specs/2026-11-13-library-browser-previews-spec.md).
Embedding evaluation is separate and paused; no embedding model/configuration changes belong in this feature.

## Verification record

- **985 tests passed**, including **21 new preview regression tests**, across knowledge_base, tasks, staff, ai_workflows and brand.test_admin_access. Test-process-only MD5 hashing accelerates tests; deployment hashing is unchanged. Initial test failures were fixture errors: explicitly double-closing Django test streaming responses closed the transactional PostgreSQL connection, and a replacement fixture omitted existing upload-authority confirmation. Corrected fixtures, then reran the full suite successfully.
- Pulled and exercised the exact pinned Gotenberg 9.5.0 image with the Compose-equivalent read-only root, private /tmp, dropped capabilities, no-new-privileges, 768 MiB/one CPU/128 PID limits, macros disabled and deny-all LibreOffice URL access. Network routing table confirms no default Internet route. No host service/production credentials or application volumes were mounted. The test harness reached the isolated bridge IP directly; production uses the internal service DNS name.
- Real synthetic DOCX headings, paragraphs and a formatted table converted to a one-page PDF; pypdf verified expected text. Exercised cold conversion through the HTTP view and subsequent private cached PDF responses. No production documents were used.
- Chromium: desktop embedded DOCX/PDF reader, mobile full-tab PDF reader, inline image and escaped text, original-file download and anonymous denial passed with no page JavaScript errors. Inspected dark/light desktop and mobile screenshots. Narrow-screen native embedded PDF rendering clipped content, so the shipped mobile UI deliberately offers a full-tab browser reader rather than a broken iframe. The test WSGI fixture needed threading because native PDF preconnects can block a single-thread test server; this is not a production configuration change.
- Browser artifacts: `/tmp/teklora-library-docx-desktop-light.png`, `/tmp/teklora-library-docx-desktop-dark.png`, `/tmp/teklora-library-docx-mobile-dark.png`, `/tmp/teklora-library-image-mobile-dark.png`, `/tmp/teklora-library-text-mobile-light.png`.
- `docker compose config --no-env-resolution --quiet` validates without loading absent local production env files; synthetic database interpolation values avoid credential exposure. Django system/migration consistency and `git diff --check` are checked before handoff.

## Release notes

No preview DB migration. Deploy updated web/maintenance workers and static assets together with the new private document-preview sidecar/network. The converter image is approximately 2.2 GB unpacked; allow disk space. Outside Compose, DOCX conversion defaults off until a trusted internal/loopback service is configured. A converter outage shows a safe retry/download explanation and leaves original evidence, extraction, approvals and embeddings unchanged. Word layout can differ due to fonts; preserve original-download fallback. Production release/smoke testing remains pending.
