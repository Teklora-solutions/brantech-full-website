"""Moving a corpus into a new embedding space, most important documents first.

Changing embedding model was designed for from the start -- `EmbeddingSpace`
exists so two models' vectors never get compared, and so a new space can be
built while the old one keeps serving. What was missing was the thing that
fills it.

Filling it is not free: every document goes to the provider again. On a corpus
large enough to matter that is a bill you may want to meet in instalments, and
a half-finished migration is only acceptable if the half that finished is the
half the agents actually use. Hence `harness/importance.py`, and hence the
ordering here.

**The other reason this exists.** `Embedding.vector` is a bare `vector` column
and pgvector will not index one; the fix is a partial index over a cast, which
caps out at 2000 dimensions. The active space is 3072, so it cannot be indexed
at any effort and every `recall()` is a sequential scan. `gemini-embedding-001`
is trained with Matryoshka representation learning, so a 1536-dimension space is
a supported truncation rather than a lossy hack -- and it is indexable. Getting
there means re-embedding, which is this module.

**On cost.** The estimate here is an estimate and says so. Tokens are
approximated from character count, because the provider does not return usage
for embeddings; and `gemini-embedding-001` has no price in the catalogue at
all, so a dollar budget cannot be enforced against it. That is reported rather
than papered over -- a budget silently enforced against a made-up price would
be worse than no budget. `--limit` bounds the work in documents, which is
always knowable.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Documents per request. The provider charges by token either way, so this
# trades round trips against how much work a failure loses.
DEFAULT_BATCH_SIZE = 64

# Characters per token, roughly, for English prose. Used only to estimate, and
# every number derived from it is labelled as one.
CHARS_PER_TOKEN = 4


@dataclass
class Plan:
    """What a re-embedding run would do, before it does any of it."""

    space: object
    documents: list = field(default_factory=list)   # [(document, score)]
    remaining: int = 0          # how many still lack a vector in this space
    deferred: int = 0           # left out of this run by a limit or a budget
    estimated_tokens: int = 0
    estimated_cost: float | None = None
    price_source: str = ""

    @property
    def count(self):
        return len(self.documents)

    def describe(self):
        cost = (
            f"~${self.estimated_cost:.4f} ({self.price_source})"
            if self.estimated_cost is not None
            else "unknown -- this model has no price in the catalogue"
        )
        return (
            f"{self.count} of {self.remaining} document(s), "
            f"~{self.estimated_tokens:,} tokens, estimated cost {cost}"
        )


@dataclass
class Report:
    """What it actually did."""

    space: object
    embedded: int = 0
    failed: int = 0
    batches: int = 0
    errors: list = field(default_factory=list)


def target_space(provider, model_id, dimensions):
    """Find or create the latest matching CLI profile.

    Model, width, billing backend and input protocol identify compatible work.
    Reusing a matching active profile repairs its missing/stale vectors rather
    than silently changing the serving model.
    """
    from knowledge_base.models import EmbeddingSpace
    from brandtechsolution.config import config

    profile = dict(provider=provider, model_id=model_id, dimensions=dimensions,
                   api_backend=config.embedding_backend, input_protocol='retrieval_v1')
    space = EmbeddingSpace.objects.filter(**profile).order_by('-created_at', '-pk').first()
    if space is not None:
        return space, False
    return EmbeddingSpace.objects.create(**profile, status=EmbeddingSpace.BUILDING), True


def pending(space, *, scope=None, kind=None):
    """Documents with no vector in `space` yet.

    This is what makes the job resumable with no state of its own: re-running
    it simply finds less to do. A run killed halfway through is resumed by
    starting it again.
    """
    from knowledge_base.library.retrieval import PROTECTED_LIBRARY_SCOPES
    # Library content requires its own current-version/clearance worker path.
    # Generic backfills have no actor, classification or provider-clearance context.
    from knowledge_base.embedding_lifecycle import pending as eligible_pending
    rows = eligible_pending(space).exclude(scope__in=PROTECTED_LIBRARY_SCOPES)
    if scope:
        rows = rows.filter(scope=scope)
    if kind:
        rows = rows.filter(kind=kind)
    return rows


def estimate_tokens(documents):
    """Roughly how many tokens these documents are. An estimate, and only that.

    The provider returns no usage for an embedding call, so there is nothing
    to measure and this cannot be reconciled after the fact.
    """
    return sum(
        (len(document.text or "") + len(document.title or "")) // CHARS_PER_TOKEN + 1
        for document in documents
    )


def price_entry(space):
    """The catalogue row that prices this space's model, or None."""
    from ai_workflows.harness.usage import price_for

    entry = price_for(space.provider, space.model_id)
    if entry is None or entry.input_price_per_mtok is None:
        return None
    return entry


def estimate_cost(space, tokens, entry=None):
    """(cost, price_source), cost None when the model has no known price.

    `entry` is accepted so a caller pricing document-by-document looks the
    model up once rather than once per document -- the difference between one
    query and one per row of the corpus.
    """
    entry = entry if entry is not None else price_entry(space)
    if entry is None:
        return None, ""
    return float(entry.input_price_per_mtok) * tokens / 1_000_000, entry.price_source


def plan(space, *, limit=None, budget_usd=None, scope=None, kind=None):
    """Choose what to re-embed, in importance order.

    A `budget_usd` against a model with no known price raises rather than
    quietly running the whole corpus. A ceiling that cannot be enforced must
    not look like one that can.
    """
    from ai_workflows.harness.importance import rank

    candidates = list(pending(space, scope=scope, kind=kind))
    ranked = rank(candidates)
    remaining = len(ranked)

    if limit is not None:
        ranked = ranked[:limit]

    if budget_usd is not None:
        entry = price_entry(space)
        if entry is None:
            raise ValueError(
                f"{space.provider}/{space.model_id} has no price in the "
                f"catalogue, so a ${budget_usd:.2f} budget cannot be enforced "
                f"against it. Use --limit to bound the work by document count, "
                f"or add the price to harness/pricing.toml and re-run "
                f"`manage.py refresh_catalogue`."
            )
        ranked = _within_budget(space, ranked, budget_usd, entry)

    documents = ranked
    tokens = estimate_tokens([document for document, _ in documents])
    cost, source = estimate_cost(space, tokens)

    return Plan(
        space=space,
        documents=documents,
        remaining=remaining,
        deferred=remaining - len(documents),
        estimated_tokens=tokens,
        estimated_cost=cost,
        price_source=source,
    )


def _within_budget(space, ranked, budget_usd, entry):
    """The most important prefix of `ranked` that fits the budget.

    Stops at the first document that would not fit rather than skipping it and
    carrying on. The list is in importance order, so continuing past it would
    quietly spend the remaining budget on less important documents than the
    one it just declined.
    """
    kept, spent = [], 0.0
    for document, score in ranked:
        cost, _ = estimate_cost(space, estimate_tokens([document]), entry)
        if cost is None or spent + cost > budget_usd:
            break
        kept.append((document, score))
        spent += cost
    return kept


def execute(plan, *, memory=None, batch_size=DEFAULT_BATCH_SIZE, on_batch=None):
    """Embed the planned documents into the plan's space.

    A failed batch is recorded and the run continues. One provider hiccup two
    thirds of the way through a long backfill should not discard the two
    thirds that worked -- and because progress is "which documents have a
    vector in this space", re-running picks up exactly what is left.
    """
    from ai_workflows.harness.memory import Memory
    from knowledge_base.models import Embedding

    from ai_workflows.harness.llm import get_embedder
    from ai_workflows.harness.embeddings import validate_vector, classify_failure
    space = plan.space
    memory = memory or Memory(embedder=get_embedder(space=space))
    report = Report(space=space)

    documents = [document for document, _ in plan.documents]
    from knowledge_base.library.retrieval import PROTECTED_LIBRARY_SCOPES
    if any(document.scope in PROTECTED_LIBRARY_SCOPES for document in documents):
        raise ValueError('Protected library records must be reprocessed through the cleared library worker.')

    for start in range(0, len(documents), batch_size):
        batch = documents[start:start + batch_size]
        report.batches += 1

        try:
            vectors = memory.embed_many(
                [_text_for(document) for document in batch], space,
            )
            if len(vectors) != len(batch):
                raise ValueError('Embedding count mismatch')
            vectors = [validate_vector(vector, space.dimensions) for vector in vectors]
        except Exception as exc:  # noqa: BLE001 - one batch, not the run
            report.failed += len(batch)
            code = classify_failure(exc).code
            report.errors.append(code)
            logger.warning(
                "[reembed] batch %d of space %s failed: %s",
                report.batches, space.pk, code,
            )
            if on_batch:
                on_batch(report)
            continue

        from knowledge_base.embedding_lifecycle import source_fence, current_vectors
        from knowledge_base.models import MemoryDocument
        with source_fence():
            for document, vector in zip(batch, vectors):
                source = MemoryDocument.objects.filter(pk=document.pk, content_hash=document.content_hash).exclude(scope__in=PROTECTED_LIBRARY_SCOPES).first()
                if source is None:
                    report.failed += 1
                    report.errors.append('SOURCE_CHANGED')
                    continue
                # A document already embedded here by a concurrent run is not
                # an error; preserve its successful checkpoint.
                if not current_vectors(space).filter(document=source).exists():
                    Embedding.objects.update_or_create(space=space, document=source, defaults={
                        'provider': space.provider, 'model_id': space.model_id, 'dimensions': space.dimensions,
                        'vector': vector, 'content_hash': source.content_hash,
                    })
                report.embedded += 1

        if on_batch:
            on_batch(report)

    return report


def _text_for(document):
    """What actually gets embedded.

    Title and body together: a document recalled by its subject should match on
    its subject, and several of these have a title that says more than the
    first paragraph does.
    """
    title = (document.title or "").strip()
    text = (document.text or "").strip()
    return f"{title}\n\n{text}".strip() if title else text


def activate(space, *, require_complete=True, embedder=None):
    """Make `space` the one queries use, in a single atomic flip.

    The old space is retired rather than deleted -- it stays queryable, and a
    validated rollback can reuse current-hash vectors rather than rebuilding
    the whole corpus a second time.

    The require_complete argument is retained for compatibility, but no longer
    permits incomplete activation. Refuses an unfinished space, because
    activating a half-filled space does not fail: it silently returns worse
    results, for the documents that happen to be missing, with nothing to
    indicate why.
    """
    from django.utils import timezone

    from knowledge_base.models import EmbeddingSpace

    missing = pending(space).count()
    if missing:
        raise ValueError(
            f'{missing} document(s) still have no vector in this space. '
            'Finish the backfill; force no longer bypasses completeness.'
        )

    from knowledge_base.embedding_lifecycle import source_fence, coverage_guard, probe_profile
    probe_profile(space, embedder=embedder)
    with source_fence():
        # Even legacy --force may not silently abandon eligible source vectors.
        coverage_guard(space)
        from knowledge_base.models import EmbeddingMigration
        if EmbeddingMigration.objects.filter(active_slot=1).exists():
            raise ValueError('A managed migration is in progress; use its administrator controls.')
        # Retire first: a partial unique index allows exactly one active space,
        # so the two statements cannot be reordered.
        EmbeddingSpace.objects.filter(
            status=EmbeddingSpace.ACTIVE,
        ).exclude(pk=space.pk).update(status=EmbeddingSpace.RETIRED)

        space.status = EmbeddingSpace.ACTIVE
        space.activated_at = timezone.now()
        space.save(update_fields=["status", "activated_at"])

    return space
