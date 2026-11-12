# Teklora document library specification

Status: user-approved scope and policies; checkout implementation completed on 2026-11-12; the library is always available to staff, with no feature toggle. Production release/security/operational acceptance remains pending. Original scope approved 2026-11-04.
Repository: `Teklora-solutions/brantech-full-website`.
Related delivery plan: [Library and EduShare task plan](../plans/2026-11-04-library-and-edushare-delivery-plan.md).

## Confirmed requirements

- A staff library for researchers' references, operational documents, meeting minutes, and reports.
- Support text documents and scanned documents/images with OCR, then embed approved extracted text for search and AI retrieval. Meeting notes/transcripts are produced externally (normally Google Meet) and uploaded as DOCX; the library does not ingest recordings or perform audio/video transcription.
- Limit: 25 MB per document/scan. Validate document-processing capacity and enforce worker/parser/time budgets before enabling production processing.
- Every upload requires administrator clearance before external OCR, embedding, or AI processing. External providers are allowed only under approved data restrictions; restricted content remains blocked.
- Keep originals until explicitly deleted. Block access immediately on deletion and purge live originals, extracted text, chunks and vectors within 30 days; separately audit backup expiry.
- Only administrators may approve documents for public consumption.
- Per-document access, defaulting to the owner and authorised administrators; explicit sharing with people, roles/groups, or the organisation.
- Embedding readiness and public approval are independent. A ready vector is never publication consent.
- Deliver in Teklora first; EduShare dashboards remain a separate delivery workstream, not a second library implementation.

## Implementation update — 2026-11-12

Execution record: [Library completion plan](../plans/2026-11-12-library-completion-plan.md).

- Domain persistence: `LibraryDocument`, `LibraryVersion`, `LibraryGrant`, `LibraryChunk`, `LibraryAudit` in the existing app; migrations `0005`/`0006`. Review history is append-only audit events linked to the exact version, with actor/time/classification/provider/reason for clearance and reason for publication decisions.
- Staff HTML interfaces: `GET /library/`, `GET|POST /library/upload/`, `GET /library/<id>/`, `GET /library/<id>/download/`, `GET /library/review/?queue=clearance|public`; mutations use CSRF-protected `POST /library/<id>/actions/<action>/` and require the current `version_id`. Invalid/stale submissions show errors without applying changes; inaccessible objects return 404 and forbidden actions return 403.
- Processing uses bounded local extraction, local Tesseract/Poppler OCR, and approved Gemini embeddings, without external OCR egress. Jobs run on a dedicated queue with 55s/60s soft/hard ceilings, independent job-generation tokens, three automatic attempts at most and explicit owner/editor retry. A worker killed mid-processing becomes a visible retryable failure through maintenance.
- One SQL ACL selector is used before search/count/pagination and eligible-chunk joins precede semantic/lexical ranking. Generic memory cannot query library scopes even explicitly. Public assistant/newsroom suites receive only the public-library tool; an internal tool factory requires trusted actor binding and must not be mounted on public/shared chat.
- All HTML/file responses are private/no-store; previews are escaped text, not rendered HTML/Markdown. Originals have no public storage URL. Administrator list/detail/retrieval accesses and downloads are audited.
- Beat maintenance every 15 minutes removes deleted documents promptly, including originals, chunks and vector memory, rather than waiting the full 30 days. Rolled-back unreferenced originals older than one day are cleaned from private storage. Real backup expiry must be operator-verified; historical retention claims below are not operational evidence.
- The operator requested removal of the feature toggle entirely. Staff pages, processing and public-approved retrieval are always available; document ACLs and per-version processing/public review gates are unchanged. No production migrations, assignments, task approvals, provider calls on real documents, or deployment were performed by this implementation.

## Original implementation baseline and gaps

Inspected at checkout `3a310f1` before this implementation:

| Existing component | Reuse / limitation |
| --- | --- |
| `knowledge_base/models.py:KnowledgeDocument` | Legacy document-wide vector and metadata; no upload ownership, ACL, version, or approval state. |
| `MemoryDocument`, `Embedding`, `EmbeddingSpace` | Reuse model provenance and active embedding spaces. Current generic-object identity supports one memory record per object, so represent each library chunk as its own object rather than mapping all chunks to the document. |
| `ai_workflows/harness/memory.py:Memory.recall` | Supports corpus/kind filters, but no user or document ACL. `scope=None` can search across corpora. Not a safe interface for private library retrieval as written. |
| `ai_workflows/tools.py:search_knowledge` | Explicitly searches editorial/site scopes. Keep library material out of these corpora; expose it through an authorised library tool. |
| `knowledge_base/services/knowledge_graph.py` | Legacy search has no document ACL, including substring fallback. Do not ingest private library material through this path. |
| Staff capability system, groups, audit; Celery/Redis | Reuse patterns, with explicit object permissions and new library audit actions. `is_staff` alone is not administrator status. |

At that baseline there was no private document library, so these were integration risks rather than evidence of an existing private-library leak.

## Proposed architecture and decisions

Extend the existing `knowledge_base` app with library domain models/services/views; do not create a competing vector store or a separate React application. Keep existing editorial/site retrieval behaviour intact.

1. **Document:** owner, title, description, category, tags, visibility, current version, timestamps, soft-deletion marker. Use explicit `related_name` and indexes for filtered state/owner fields.
2. **Version:** immutable private storage key, original filename, detected format, size, checksum, extraction/index status, safe error code, and uploader. Initial scope: PDF, DOCX, TXT, Markdown and scanned PDF/JPEG/PNG. Google Meet-exported meeting notes are ordinary DOCX documents. OCR is included; recording uploads, audio/video processing and transcription adapters are excluded. LIB-01 must pin document MIME validation, provider and worker/resource budgets. Slides and spreadsheets remain outside the agreed scope.
3. **Grant:** document + user or group, with an explicit read or edit level and uniqueness constraints. Organisation sharing means authenticated active staff, not all public signup accounts. Editors do not implicitly gain share, delete, or publication rights; owner/admin controls those.
4. **Chunk:** version, ordinal, extracted text, page/section reference, content hash. Link each chunk to existing semantic-memory records using a dedicated library corpus. Authoritative ACL stays in relational models, not editable vector metadata.
5. **External-processing clearance:** per-version administrator decision, classification, permitted provider/purpose, reviewer/time/reason. States: `pending`, `approved`, `rejected`. Before clearance, files remain quarantined privately and are neither sent to providers nor embedded. Local bounded validation/scanning is permitted. Replacement invalidates clearance. Record document upload-authority confirmation; missing authority blocks processing. Clearance does not grant public use.
6. **Approval:** version, state (`not_reviewed`, `pending`, `approved`, `rejected`), requester/reviewer, timestamps, reason. Approval attaches to exact content and public metadata. Replacement or public-facing metadata edits invalidate approval and public retrieval eligibility. Revocation records a new audited state transition.

Alternatives rejected: a single `is_public` flag cannot express review/version history; separate internal/public vector copies increase stale-copy risk; putting private text in editorial/site scopes bypasses the intended boundary. Prefer one indexed copy with authoritative query-time authorisation.

## Authorisation rules

- Anonymous users never access internal library listing, previews, files, or metadata.
- Active authenticated staff read only owned, explicitly shared, organisation-shared, or authorised-admin documents. Group membership and account deactivation take effect at request time.
- Public AI retrieval requires current-version approval, non-deleted document, ready chunks, and an explicitly public retrieval context. Approval does not expand private editing rights.
- Internal AI requires server-derived actor identity and exactly the same read policy as downloads. Missing actor/context fails closed; model-supplied user IDs, role names, or tool arguments cannot establish access.
- Apply ACL/version/state predicates before ranking/limit and before text reaches a model. Lexical fallback, counts, snippets, citations, exports, preview, and download paths use the same policy.
- Generic unscoped memory recall must exclude protected library records unless called through the authorised library retrieval service. Library-specific kinds/scopes must not become a caller-controlled bypass.
- Confirmed approval rule: active superuser or active staff in the canonical Administrator role with a new `approve_library_publication` permission. The same administrator boundary controls external-processing clearance and private-document oversight. A delegated capability alone is insufficient; never infer administrator status from `is_staff` or a UI label. A document owner is not a platform Owner and cannot approve merely because they uploaded it.
- Authorised administrators may inspect private documents for review; audit those accesses. No self-service escalation through group editing or document grants.

## Upload, processing, and lifecycle

1. Validate size, extension, detected content, filename, and parser limits; reject executable/HTML uploads and unsupported/encrypted/unreadable formats with clear errors. Keep files outside public media/static paths; use authenticated streaming endpoints with safe content disposition.
2. Commit quarantined private metadata with processing clearance pending. Only after administrator clearance, enqueue document extraction/OCR/indexing after commit. Processing states: `awaiting_clearance`, `queued`, `processing`, `ready`, `failed`, `blocked`; extraction failure never sets ready. Provide retry with bounded backoff and useful user-visible errors, without raw document text in logs.
3. Extract using existing PDF/DOCX dependencies and approved OCR adapters, normalise and chunk with page/section provenance, then embed through the configured model harness. Enforce document size, parser, concurrency and cost limits; never send uncleared content to an external provider. Use idempotency keys per version/content hash/embedding space.
4. Validate version and deletion state before publishing worker output. Replacement/deletion races cannot restore old content. Model-space migration reuses provenance and preserves ACL/version joins.
5. Request public review, inspect original and extraction, then approve/reject server-side as an administrator. UI label is `Administrator-approved for public use`, not a guarantee of legal clearance or factual accuracy.
6. Revoke, delete, or change sharing: new retrieval/download requests immediately consult current state. Hide results synchronously; clean files/chunks/vectors asynchronously with retries. Do not depend on cleanup finishing to enforce revocation.
7. Permission-aware caches include audience, actor/ACL version, document version, and approval state; invalidate on changes. Do not replay private tool outputs to another user or public chat. Already delivered answers/downloads cannot be retroactively withdrawn; document this limitation.

## Privacy and AI safety

- Public approval review checks personal data, meeting confidentiality, copyright/licensing, and redaction needs; default private is not a substitute for review.
- Private text may go to an external embedding/model provider. LIB-01 must approve provider processing/retention and data classification before enabling indexing; unsupported sensitive classes remain blocked.
- Treat uploaded text as untrusted evidence, never system instructions or authority to invoke tools/change permissions. Cite permitted document/version/page references only.
- Audit upload, sharing, review, approval/rejection/revocation, replacement, deletion, retry, and administrative access without storing document bodies/secrets in telemetry.
- Retain originals until deletion; inaccessible deleted content must be purged from live storage within 30 days, including derived text, vectors and caches. Audit and publish backup-expiry rules before release; avoid claiming immediate erasure from immutable backups.

## UI acceptance

The [2026-11-12 UI redesign](2026-11-12-library-ui-redesign-spec.md) replaces the original scaffold with shared-theme components, permission-scoped summaries, filterable document rows, role-aware tabs and distinct empty states. Uploads retain native form behavior with progressive drag-and-drop/progress/error handling; detail screens separate preview, facts, sharing, editing and independent administrator decisions. Browser verification is recorded in the [redesign execution plan](../plans/2026-11-12-library-ui-redesign-plan.md).

Library list/search, upload, details/preview/download, share editor, external-processing clearance queue and separate public-review queue use existing Django templates and panel conventions. Display independent processing and approval badges, owner/category, access summary, and accessible error/empty/loading states. Unauthorised users must not learn titles/counts via search or badges. Public approval need not expose an anonymous original-file URL; v1 public use is approved AI retrieval with safe citation metadata.

## Verification and release gates

- Owner, selected user/group, organisation staff, unrelated staff, deactivated users, anonymous callers, administrators, and non-admin capability holders covered by tests.
- Verify direct-object requests and every retrieval/fallback path deny inaccessible text/metadata; generic `scope=None` cannot reveal library records.
- Test pending/rejected/replaced/revoked/deleted documents against public AI; test group removal and permission revocation against internal AI and caches.
- Test malformed/oversized/unsupported files, rejected audio/video uploads, OCR/extraction/embedding errors, retries, duplicate jobs, deletion/replacement during processing, and embedding-space changes. Assert zero external provider calls before administrator processing clearance and zero public retrieval before the separate publication approval.
- Test prompt injection, tool actor spoofing, session/citation reuse, CSRF, upload/download safety, migration/rollback, and safe audit content.
- Use stub providers in automated tests and a dedicated PostgreSQL/pgvector test database for vector integration. Run `python manage.py test knowledge_base ai_workflows staff tasks` in the configured development environment, not production.
- David signs off security and retrieval isolation; Mugisha accepts operational workflow. There is no library feature toggle. Staff authentication, document permissions, processing clearance and separate public approval enforce the security boundary; operational verification is part of deployment, not a feature opt-in.
