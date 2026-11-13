# Embedding lifecycle execution plan

Status: Implemented and verified locally after the user's power outage. User authorized commit and push in the follow-up; deployment and separate live Vertex evaluation remain pending.

- [x] Confirm desired mostly-automatic recovery/migration with administrator visibility/control.
- [x] Inspect existing processing/reembed/activation/query behavior; identify lost partial work, protected-library coverage gap, global-model client coupling and missing explicit Vertex embedding route.
- [x] Record lifecycle, billing-route, privacy and activation invariants before implementation.
- [x] Add immutable profile metadata, durable source-hash work/checkpoint records and migration state; generate/test migrations.
- [x] Implement explicit Google embedding adapters for Vertex and Developer API, correct model-specific retrieval protocols and space-bound query clients without fallback.
- [x] Add automatic reconciliation, fenced per-document work, safe retries/leases, library extraction checkpointing and complete-coverage activation/rollback.
- [x] Add private, CSRF-protected administrator controls and progress/failure views; preserve ordinary staff permissions.
- [x] Integrate periodic coordinator, worker credentials and legacy CLI safety guards.
- [x] Run regression/concurrency/migration tests and browser verification; update required release documentation.

## Verification and limitations

- Added 52 client/lifecycle/concurrency/migration/legacy-interface tests, plus one new logging regression; existing assertions were updated for durable retained extraction, immutable profiles, zero-vector rejection and presence-only secret diagnostics.
- Final core app command (`knowledge_base ai_workflows tasks staff`): **1,032 tests passed**, including existing browser-preview regression coverage. MD5 password hashing was used only by the test runner.
- Final all-affected-app command (the same apps plus `editorial`): **1,157 tests, one failure**. The unchanged `editorial.tests.test_approval.NotifyEditorsTest.test_every_publish_blog_holder_is_notified` expects one grouped email but current code sends two individual recipient emails. It also fails on untouched `HEAD`.
- An earlier full repository run exposed additional unrelated Brand failures (obsolete Project fields, old API response/HTML expectations and SQLite-specific index checks). A detached unchanged-HEAD baseline reproduced **14 failures/errors in 39 representative tests**, including the editorial email expectation. Do not describe the complete repository test suite as green. No unrelated production behavior was changed to satisfy stale tests.
- PostgreSQL/pgvector tests exercise real separate-connection worker/admin races and `0006 → 0008 → 0006 → 0008` migration application with preserved vector values and provenance backfill.
- Isolated Chromium admin UAT: actual cost-consent/target forms, Vertex/model-2 selection, pause/resume, background build to ready, explicit activation, actual partial HNSW index creation/validation, retained-vector rollback, staff/anonymous denial, 390px and desktop light/dark screenshots, no page JavaScript errors. All provider responses were deterministic offline fakes; Google/provider credentials were mocked; no provider requests or real staff documents were used.
- Django system check, migration drift check, Compose validation with synthetic environment and `git diff --check` passed. No non-test database or production migrations were applied; migration tests/browser fixture used isolated test databases.
- Screenshots: `/tmp/teklora-embedding-{start-desktop-light,ready-desktop-dark,ready-mobile-light,ready-mobile-dark}.png`. Core/final-all-affected logs: `/tmp/teklora-embedding-final-core-tests.log`, `/tmp/teklora-embedding-final-all-affected-tests.log`.
- Native API requests are bounded and SDK transport retries are disabled; DNS/OS resolution and uncertain already-in-flight provider requests cannot be made exactly-once. Legacy batch CLI backfills retain their batch failure semantics; use the managed workflow for durable per-source recovery. No live quality/latency/cost/credit result is claimed.

Keep completed browser-preview work intact. The user's follow-up authorizes committing and pushing the completed changes. Separate Vertex evaluation remains pending; do not report fabricated measurements. No production model switch, paid corpus job or deployment is authorized here; the user handles deployment.
