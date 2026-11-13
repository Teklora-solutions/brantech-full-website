# Vertex embedding evaluation plan

Status: Paused while implementing the user's browser-preview request. The first Vertex credential/model probe exceeded its 90-second command deadline without producing results; this is not evidence that either model is unavailable. No completed benchmark or production changes. Authorized: bounded evaluation, not model promotion/deployment.

1. [x] Inspect source configuration and installed SDK; verify credential presence without displaying values. Service-account credential file and Developer API key both exist; explicit Vertex project is blank, so derive billing/routing project from the service-account file. Do not use Developer API fallback.
2. [ ] Probe both stable models through Vertex using the configured location. If a documented regional route is needed, record that route explicitly rather than changing production configuration.
3. [ ] Freeze a sanitized English/Swahili retrieval fixture with confusable documents and relevance labels; implement a bounded standalone Vertex-only runner and offline unit tests.
4. [ ] Execute paired model/dimension evaluation and a separate visual capability smoke test if access permits. Save metrics/rankings without vectors or credential metadata.
5. [ ] Run affected-app tests and checks; document measured outcomes, failures, pricing caveats, sampling limitations and recommendation. Update CHANGELOG, ROADMAP and README.

Contract: [specification](../specs/2026-11-13-vertex-embedding-evaluation-spec.md).
