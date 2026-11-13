# Vertex embedding comparison contract

## Scope and safety
Compare `gemini-embedding-001` with `gemini-embedding-2` through the standard billed Vertex AI route, using configured service-account credentials and their project (or explicit configured Vertex project). Never silently fall back to the Gemini Developer API: production credits are on Vertex. The runner does not initialize Django, query a database, change active spaces, or persist embeddings. Never print credentials, access tokens, project IDs or service-account identity.

Use only committed, explicitly synthetic evaluation documents/questions and public/sanitized multimodal fixtures. No staff uploads, submissions, private library documents, logs or personal data. Cap online calls at 160 and total submitted text characters at 250,000; one attempt per SDK request, finite HTTP timeout, bounded failure reporting. Stop on authentication/model access failures rather than invent results. Actual credits consumed cannot be inferred from list pricing; do not claim billing verification without billing evidence.

## Experiment
- Evaluate exact cosine search (not ANN) using identical documents and human-authored English/Swahili queries, explicit relevant document IDs, difficult neighboring/distractor documents, and frozen order/seed.
- Compare independently requested 768- and 1536-dimensional vectors. Both models must return one finite, nonzero vector of the expected width per input. Normalize locally for consistent cosine scoring.
- Use RETRIEVAL_DOCUMENT/RETRIEVAL_QUERY for 001; use documented retrieval text prompts and omit task_type for 2. Isolate spaces by model/dimension.
- Report top-1 hit rate, Recall@5 and MRR@10, per-language breakdowns, per-query rankings, failures, wall-clock latency samples and p50/p95, actual token usage where provided, and token-based list-price estimates separately from billed cost.
- Repeated query calls measure small-sample client-observed latency, not production load, throughput or provider-side compute alone. Record cold calls separately.
- Optional synthetic visual PDF/image smoke evaluation is a separate capability experiment, not an unfair native-input comparison against text-only 001.

## Acceptance and limits
Commit reproducible fixtures, runner and offline regression tests. Record real results, model/region access limitations, corpus size, limitations of synthetic queries and a migration recommendation. Do not promote either model based on a tiny curated corpus; representative approved-corpus evaluation remains a release gate. No migration, deploy, commit, push or production task mutation is authorized by the evaluation request.
