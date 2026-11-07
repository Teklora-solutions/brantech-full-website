# First-wave task register

Created in production Teklora Admin Tasks on 2026-11-04 with the user's authorisation. Initial tasks #32–#38 plus Emmanuel's released task #40 are Open, single-assignee and have no due date. Emmanuel's profile/onboarding was subsequently verified and his held Brantech task was assigned. The policy/spec files are published on documentation branches for team access; task descriptions also include self-contained scope, policy, acceptance and dependency details.

| Task | Planning key | Repository | Assignee | Depends on |
| --- | --- | --- | --- | --- |
| #32 | W1-LIB-POLICY | Teklora-solutions/brantech-full-website | mugishalionel | None |
| #33 | W1-LIB-ACL | Teklora-solutions/brantech-full-website | davidnjihia | #32 classification examples; contract/testing can start now |
| #34 | W1-LIB-MODELS | Teklora-solutions/brantech-full-website | juniorkariuki | #32 and #33 agreed policy/interface outputs; discovery starts now |
| #35 | W1-LIB-UI | Teklora-solutions/brantech-full-website | jmunuve | #33/#34 contract; fixture UI before completed backend; real integration afterwards |
| #36 | W1-EDU-STUDENT | Teklora-solutions/school | leonmusungu | None; audit + small verified fixes |
| #37 | W1-EDU-ADMIN | Teklora-solutions/school | juniorkariuki | None technically; bounded triage during library discovery/waits |
| #38 | W1-EDU-UAT | Teklora-solutions/school | mugishalionel | None; parallel sanitised acceptance cases |
| #40 | W1-LIB-REVIEW-UI | Teklora-solutions/brantech-full-website | emmanuellamira | #33/#34 contract and endpoints; coordinate component boundaries with #35 |

The board has no native blocked state. Dependency outputs, not whole-task closure, gate later work; descriptions/activity record progress. Do not report waiting tasks as completed. David's own implementation should be reviewed by Junior; David retains review/deployment as the default across streams.

Creation used the application's TaskSerializer, assignment syncing and activity recording inside an atomic transaction, after verifying David's manage_tasks permission and each assignee's active staff/onboarded status. Each task is source=manual. Existing task records were not modified during creation. A subsequent user-authorised scope correction updated library tasks #32–#35 and #40 as recorded below. No notification emails or GitHub issues were requested or sent by this operation.

School was already registered as repository #7. Teklora's canonical repository was absent, so it was registered to link these tasks; automatic roadmap imports were left disabled for that new repository to avoid duplicating manually issued packets. Existing School repository settings were unchanged. No account permissions, deployed application files, migrations, or service settings changed.

Specs:
- [Teklora library](../specs/2026-11-04-document-library-spec.md).
- EduShare: `school/docs/specs/2026-11-04-dashboard-audit-and-targeted-fixes-spec.md` in the separate School checkout.
- [Overall sequencing](2026-11-04-library-and-edushare-delivery-plan.md).

Emmanuel follow-up: active onboarded profile `emmanuellamira`, GitHub `VPOUR`, Fullstack Engineer. Recorded stack: Bash/Shell, C/C++, Dart, HTML/CSS, TypeScript; Docker, Electron, Express.js, Flutter, Git/GitHub Actions, MongoDB, Next.js, Node.js, OpenAI/Claude APIs, React, Tailwind CSS. GitHub permission check returned Brantech read access (no direct push confirmed) and School none. Task #40 supports a public-repo fork/PR workflow or a separately approved write-access grant. No School assignment or permission changes were made.

Scope correction: live tasks #32–#35 and #40 were edited before documentation to remove recording ingestion, transcription pipelines, recording consent, codecs, 250 MB and duration limits. Task #32 is now titled `Library classification, upload authority and acceptance cases`. Meeting notes/transcripts arrive externally as DOCX (normally Google Meet); retain PDF/DOCX/TXT/Markdown, scanned documents/images and OCR, with a 25 MB per-document/scan limit. Existing administrator processing clearance and separate public approval remain. Each edited task has an activity entry; statuses, assignees and dependencies were preserved. EduShare task descriptions were not changed.

Implementation and deployment remain pending. No feature code was implemented by issuing these tasks.
