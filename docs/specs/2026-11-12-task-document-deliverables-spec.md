# Task document deliverables — implementation contract

Implements the existing task-deliverables plan in the Django Tasks workspace without changing live tasks or deploying. Existing tasks retain `standard` completion. Managers may choose `document`, `code`, or `either` delivery; requirements cannot change after assignment completion/submission or on Done tasks.

## Data and privacy
TaskSubmission is an immutable assignment-specific round (nullable retained assignment/submitter links, task, revision, note, idempotency UUID, timestamp). Attachments reference exact nullable LibraryVersion rows; original files are never copied and privacy purge is never blocked. Append-only review events record acceptance/changes and feedback. Latest round per live assignment is authoritative; reassignment cannot inherit past rounds. Submission-only access never expands library/AI retrieval permissions.

## API (under /api/work/tasks/<id>/)
- GET/POST `deliverables/`: private actor-filtered history / submit `{version_ids, note, expected_submission_id, request_id, share_confirmation}`. Multiple versions (max 10); selection must still be current and share-authorized under row locks. Submit marks only the caller's assignment complete. Retry UUID prevents duplicate rounds.
- POST `deliverable-upload/`: multipart `original`, `title`, `authority`; creates an ordinary private library document only. Upload does not complete work. Failed final submission preserves the uploaded document.
- GET `deliverable-documents/?q=&page=`: paginated shareable current documents for assignees only.
- POST `review-deliverable/`: manager-only `{submission_id, decision: accepted|changes_requested, feedback}`; feedback required for changes. Stale/superseded or unassigned rounds cannot be reviewed. Changes reset only the relevant assignment.
- GET `deliverable-file/<attachment_id>/`: active reviewer or original still-assigned submitter; attachment-only pinned-version download, no-store and audit; deleted/purged evidence is unavailable. Other board readers cannot see notes, filenames, counts or feedback.

Completion validation is reused by API and GitHub/roadmap/documentation automation. New code/either requirements accept only default-branch TaskCommit evidence attributed to that assignee (explicit team associations deferred; no implicit task-wide attribution). Document evidence must be available and not changes-requested. Approval requires complete assignments and accepted current document rounds. Whole-task reopen records fresh-review requirements for current rounds; Done tasks reject submissions/reviews/uploads. No external AI calls or clearance/public approval from submission/acceptance.

UI adds private Deliverables history, upload/library selection, notes and explicit reviewer-audience consent, exact-version downloads, accept/request-changes and delivery requirement selection. Native labelled controls, inline status/error messages and duplicate-submit protection preserve form data on recoverable errors. Notifications contain no private evidence metadata. Browser/automated verification and any release limitations are recorded in the plan.
