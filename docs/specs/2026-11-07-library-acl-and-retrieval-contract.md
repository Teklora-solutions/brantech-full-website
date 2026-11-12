# Library ACL & Retrieval Contract Specification (Task #33)

- **Task**: `[Task #33] [W1-LIB-ACL] Implement library ACL and retrieval contract foundation`
- **Owner**: David Njihia (`davidnjihia` / GitHub `BigAddict`)
- **Reviewer**: Junior Kariuki (`juniorkariuki`)
- **Repository**: `Teklora-solutions/brantech-full-website`
- **Status**: Contract agreed & foundation implemented with passing tests (`knowledge_base.tests`).

---

## 1. Executive Summary & Purpose

This document defines the canonical interface contract, policy matrix, capacity parameters, and safe retrieval foundation for the Teklora Staff Document Library. It establishes:
1. Deny-by-default access control across all document operations.
2. Separation of document ownership from administrator approval authority.
3. Strict gating: **zero external provider calls without administrator clearance**, and **no public retrieval without version publication approval**.
4. Isolation of generic memory recall (`scope=None`) to prevent library text leakage.
5. In-memory stubs and fixtures (`knowledge_base.library.stubs`) enabling Junior (LIB-02/03 backend) and jmunuve/Emmanuel (LIB-05/06 UI) to implement and test against an authoritative contract.

---

## 2. Agreed Domain Contracts & Schema

All entities are codified in `knowledge_base.library.contracts`:

### 2.1 Document Contract (`DocumentContract`)
- `id` (int, Primary Key): Unique document identifier.
- `owner_id` (int, Foreign Key -> `auth_user`): Author/uploader of the document.
- `title` (str, max 300 chars): Human-readable title.
- `description` (str): Abstract or context description.
- `category` (str, default `"general"`): Functional category (e.g., `research`, `operations`, `minutes`, `reports`).
- `tags` (list[str]): Categorization keywords.
- `visibility` (`DocumentVisibility`):
  - `PRIVATE`: Default. Accessible only to owner, explicit grantees, and administrators.
  - `ORGANISATION`: Accessible to all active authenticated staff members.
- `is_deleted` (bool, default `False`, indexed): Soft-deletion flag. Immediate synchronous access revocation.
- `current_version_id` (Optional[int]): Pointer to active version.

### 2.2 Version Contract (`VersionContract`)
- `id` (int, Primary Key): Unique version record.
- `document_id` (int, Foreign Key -> `Document`): Parent document.
- `version_number` (int): Sequential version counter (1, 2, ...).
- `storage_key` (str): Private immutable storage path (outside public static/media roots).
- `original_filename` (str): Filename as uploaded.
- `detected_format` (str): Validated MIME/extension (`pdf`, `docx`, `txt`, `md`, `png`, `jpeg`).
- `size_bytes` (int): Validated file size (max 25 MB).
- `checksum_sha256` (str): Cryptographic digest for deduplication and integrity.
- `processing_state` (`ProcessingState`): `awaiting_clearance` -> `queued` -> `processing` -> `ready` / `failed` / `blocked`.
- `clearance_state` (`ProcessingClearanceState`): `pending` -> `approved` / `rejected`.
- `public_approval_state` (`PublicApprovalState`): `not_reviewed` -> `pending` -> `approved` / `rejected` / `revoked`.
- `safe_error_code` (str): Sanitized error indicator (no raw exception or document text).
- `uploader_id` (int): User who committed this version.

### 2.3 Grant Contract (`GrantContract`)
- `id` (int, Primary Key).
- `document_id` (int, Foreign Key).
- `user_id` (Optional[int], Foreign Key -> `auth_user`): Direct user grant.
- `group_id` (Optional[int], Foreign Key -> `auth_group`): Group grant.
- `access_level` (`AccessLevel`):
  - `READ`: Metadata inspect, text chunk view, raw file stream/download.
  - `EDIT`: Update title/desc, upload new version. (Does **not** grant share, delete, clear processing, or approve public).
- *Constraint*: Exactly one of `user_id` or `group_id` must be non-null; unique per `(document_id, user_id)` and `(document_id, group_id)`.

### 2.4 External Processing Clearance Record (`ProcessingClearanceRecord`)
- `version_id` (int): Target version.
- `state` (`ProcessingClearanceState`): `pending`, `approved`, `rejected`.
- `classification` (str): Data classification (e.g. `internal_standard`, `confidential`, `restricted_pii`).
- `permitted_provider` (str, default `"gemini"`): Approved external model provider.
- `reviewer_id` (int, Foreign Key): Administrator user.
- `reviewed_at` (datetime): Timestamp.
- `reason` (str): Audit justification.

### 2.5 Public Approval Record (`PublicApprovalRecord`)
- `version_id` (int): Target version.
- `state` (`PublicApprovalState`): `not_reviewed`, `pending`, `approved`, `rejected`, `revoked`.
- `requester_id` (Optional[int]): Staff member requesting publication.
- `reviewer_id` (Optional[int]): Administrator user who approved or rejected.
- `requested_at` / `reviewed_at` (datetime).
- `reason` (str): Audit justification.

### 2.6 Chunk Contract (`ChunkContract`)
- `id` (int, Primary Key).
- `version_id` (int), `document_id` (int).
- `ordinal` (int): Chunk sequence in document.
- `text` (str): Extracted plain text segment.
- `page_or_section` (str): Provenance identifier (e.g. `"Page 3"`, `"Section 2.1"`).
- `content_hash` (str): SHA-256 of text.
- `memory_document_id` (Optional[int]): Linked pgvector `MemoryDocument` (quarantined under `scope="library"`).

---

## 3. Authorization Matrix

| Actor / Context | Read Metadata | Stream / Download | Edit Document | Manage Sharing | Soft Delete | Clear Processing | Approve Public | Public Retrieval |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Document Owner** | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ❌ Denied (`ADMIN_REQUIRED`) | ❌ Denied (`ADMIN_REQUIRED`) | ❌ If not public-approved |
| **Administrator** (Superuser or Admin group + `approve_library_publication`) | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ Allowed | ✅ (As public or internal) |
| **User with Edit Grant** | ✅ Allowed | ✅ Allowed | ✅ Allowed | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ If not public-approved |
| **User with Read Grant** | ✅ Allowed | ✅ Allowed | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ If not public-approved |
| **Group Member** (Group grant) | ✅ Allowed | ✅ Allowed | ✅ If Edit grant | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ If not public-approved |
| **Organisation Staff** (`visibility=ORGANISATION`) | ✅ Allowed | ✅ Allowed | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ If not public-approved |
| **Unrelated External User** (`is_staff=False`) | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ✅ Only if public-approved |
| **Anonymous User** | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ✅ Only if public-approved |
| **Deactivated User** (`is_active=False`) | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied |
| **Soft-Deleted Document** | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied | ❌ Denied |

---

## 4. Operational & Capacity Findings

### 4.1 Document-Processing Capacity & Budgets
1. **File Size Limit**: Strict 25 MB per document/scan. Uploads exceeding 25 MB are rejected at the edge/view layer before disk commitment.
2. **Supported Formats**: PDF, DOCX, TXT, Markdown, and scanned PDF/PNG/JPEG. Google Meet exported meeting notes arrive as standard DOCX files.
3. **Excluded Media**: Audio/video ingestion, streaming recordings, audio codecs, and video transcription are strictly out of scope and rejected immediately.
4. **Worker Concurrency**: Document extraction, OCR, and embedding run on a dedicated Celery queue (`library_processing`) with worker concurrency capped at 2 parallel extraction processes to prevent memory pressure on dev/prod droplets.
5. **Processing Timeouts**: 60-second execution budget per document. OCR processing capped at a maximum of 30 pages per scan. Documents exceeding time or page limits transition to `ProcessingState.FAILED` with safe error code `TIMEOUT_EXCEEDED` or `PAGE_LIMIT_EXCEEDED`.

### 4.2 External Provider Restrictions & Data Classification
1. **Clearance Gate**: Zero external API calls (Gemini embeddings or OCR models) may be dispatched until an active Administrator explicitly records `ProcessingClearanceState.APPROVED`.
2. **Pre-Clearance Quarantine**: Uploaded files remain stored in private storage without being sent to any third-party API.
3. **Restricted Classifications**: Documents containing unredacted national identification numbers, credit card numbers, or plaintext banking credentials must be classified as `restricted_pii` and marked `ProcessingClearanceState.REJECTED` (`ProcessingState.BLOCKED`).

### 4.3 Backup-Expiry & 30-Day Purge Findings
1. **Synchronous Immediate Invalidation**: Setting `is_deleted = True` synchronously cuts off all internal and public retrieval, streaming, and metadata viewing.
2. **Asynchronous 30-Day Purge**: A scheduled Celery maintenance task purges underlying storage files, extracted text, chunk rows, vector embeddings, and search caches for documents deleted more than 30 days prior.
3. **Backup Release Gate**: Verify the actual database AND original-file backup configuration with the operator before release. The earlier assertion of a rolling 30-day production snapshot policy was not supported by operational evidence in this checkout. Live-store purge does not establish backup erasure or legal compliance. Record observed retention, restore/redeletion procedures and expiry evidence; keep release acceptance pending until verified.

---

## 5. Generic Memory Isolation

The AI harness memory system (`ai_workflows/harness/memory.py:Memory.recall`) has been hardened:
- Protected library documents are isolated in `PROTECTED_LIBRARY_SCOPES = ("library", "staff_library")`.
- Generic unscoped queries (`scope=None`) automatically exclude protected library scopes via `rows.exclude(document__scope__in=PROTECTED_LIBRARY_SCOPES)`.
- Library records can only be queried through the authorized `LibraryRetrievalEngine`. The 2026-11-12 implementation also excludes protected scopes from explicitly scoped generic recall: a scope string is not authorization. Database retrieval joins current-version, readiness, clearance and actor/public approval predicates before ranking.

---

## 6. Handoff to Team Members

- **Junior Kariuki (`juniorkariuki` - Task #34 LIB-02/03)**:
  - Implement relational models in `knowledge_base/models.py` adhering to `contracts.py`.
  - Wire `LibraryPolicy.evaluate(...)` into list, detail, and download views.
  - Implement the Celery extraction pipeline honoring `LibraryPolicy.can_call_external_provider(version)`.
- **jmunuve & Emmanuel (`emmanuellamira` - Tasks #35 & #40 LIB-05/06)**:
  - Build UI browse/upload/detail templates and review queue using `stubs.create_test_scenarios()` as mock fixtures.
  - Render clearance badges (`Awaiting Clearance`, `Cleared`, `Blocked`) independently from publication badges (`Internal Only`, `Approved for Public`).
