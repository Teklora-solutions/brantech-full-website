"""Changing embedding model, and the index that depends on it.

Two problems that turn out to be one. `MemoryDocument.retrieval_count` has been
written on every recall since the memory layer was built and read by nothing,
though its own docstring says it is "the input to the importance score that
decides what gets re-embedded first when the model changes". And every
`recall()` has been a sequential scan, because pgvector caps an hnsw index at
2000 dimensions and the active space was 3072 -- so the only route to an index
is a narrower space, which means re-embedding.

No provider is touched: the embedder is a stub.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ai_workflows.harness import reembed
from ai_workflows.harness.importance import HALF_LIFE_DAYS, importance, rank
from ai_workflows.harness.memory import Memory
from knowledge_base import indexes
from knowledge_base.models import Embedding, EmbeddingSpace, MemoryDocument

NARROW = 8


class StubEmbedder:
    """Deterministic vectors at whatever width it is asked for."""

    def __init__(self):
        self.widths = []
        self.batches = []

    def embed_query(self, text, output_dimensionality=None):
        width = output_dimensionality or NARROW
        self.widths.append(width)
        vector = [0.0] * width
        vector[abs(hash(text)) % width] = 1.0
        return vector

    def embed_documents(self, texts, output_dimensionality=None):
        self.batches.append(list(texts))
        return [self.embed_query(text, output_dimensionality) for text in texts]


def _document(title="doc", retrievals=0, days_old=0.0, scope="default", kind="article"):
    document = MemoryDocument.objects.create(
        scope=scope, kind=kind, title=title, text=f"the text of {title}",
        retrieval_count=retrievals,
    )
    when = timezone.now() - timedelta(days=days_old)
    MemoryDocument.objects.filter(pk=document.pk).update(
        last_retrieved_at=when if retrievals else None, updated_at=when,
    )
    return MemoryDocument.objects.get(pk=document.pk)


class ImportanceTests(TestCase):

    def test_a_document_the_agents_use_outranks_one_they_do_not(self):
        """The signal nothing else in this codebase has.

        View counts measure human attention; this measures what the agents
        reach for.
        """
        used = _document("used", retrievals=20)
        unused = _document("unused", retrievals=0)
        self.assertGreater(importance(used), importance(unused))

    def test_use_is_logarithmic_not_linear(self):
        """Nought versus five retrievals is a real distinction; a hundred
        versus a hundred and five is noise."""
        low = importance(_document("a", retrievals=5))
        high = importance(_document("b", retrievals=10))
        much_higher = importance(_document("c", retrievals=1000))
        self.assertLess(high - low, much_higher - high)
        self.assertLess(much_higher, low * 4)

    def test_a_stale_document_sinks_however_popular_it_once_was(self):
        """The question is what is worth embedding *now*."""
        old_favourite = _document("old", retrievals=50, days_old=365)
        recent = _document("recent", retrievals=2, days_old=0)
        self.assertGreater(importance(recent), importance(old_favourite))

    def test_freshness_halves_over_the_half_life(self):
        fresh = _document("fresh", retrievals=4, days_old=0)
        halved = _document("halved", retrievals=4, days_old=HALF_LIFE_DAYS)
        self.assertAlmostEqual(importance(halved), importance(fresh) / 2, places=2)

    def test_nothing_scores_zero(self):
        """A corpus that can never finish migrating is a worse failure than a
        slow one."""
        forgotten = _document("forgotten", retrievals=0, days_old=3650)
        self.assertGreater(importance(forgotten), 0.0)

    def test_ranking_puts_the_most_important_first(self):
        _document("meh", retrievals=1)
        _document("vital", retrievals=100)
        _document("middling", retrievals=10)
        ordered = [d.title for d, _ in rank(MemoryDocument.objects.all())]
        self.assertEqual(ordered, ["vital", "middling", "meh"])

    def test_a_brand_new_document_is_not_buried_by_never_being_used(self):
        # It has not had the chance to be recalled yet.
        new = _document("new", retrievals=0, days_old=0)
        old_and_used = _document("old", retrievals=3, days_old=200)
        self.assertGreater(importance(new), importance(old_and_used))


class PlanTests(TestCase):

    def setUp(self):
        self.space, _ = reembed.target_space("gemini", "stub-embed", NARROW)

    def test_a_space_is_provider_model_and_width_together(self):
        """The same model at two widths produces vectors that cannot be
        compared, so they are two spaces."""
        other, created = reembed.target_space("gemini", "stub-embed", NARROW * 2)
        self.assertTrue(created)
        self.assertNotEqual(other.pk, self.space.pk)

    def test_only_documents_missing_from_this_space_are_planned(self):
        done = _document("done")
        _document("todo")
        Embedding.objects.create(
            space=self.space, document=done, provider="gemini",
            model_id="stub-embed", dimensions=NARROW, vector=[1.0] + [0.0] * (NARROW - 1),
        )
        titles = [d.title for d, _ in reembed.plan(self.space).documents]
        self.assertEqual(titles, ["todo"])

    def test_a_limit_takes_the_most_important_prefix(self):
        _document("minor", retrievals=1)
        _document("major", retrievals=99)
        plan = reembed.plan(self.space, limit=1)
        self.assertEqual(plan.count, 1)
        self.assertEqual(plan.documents[0][0].title, "major")
        self.assertEqual(plan.deferred, 1)

    def test_a_budget_against_an_unpriced_model_refuses(self):
        """A ceiling that cannot be enforced must not look like one that can."""
        _document("a")
        with self.assertRaises(ValueError) as caught:
            reembed.plan(self.space, budget_usd=5.0)
        self.assertIn("no price in the catalogue", str(caught.exception))

    def test_a_budget_is_honoured_when_the_model_is_priced(self):
        from decimal import Decimal

        from ai_workflows.models import CatalogueEntry

        CatalogueEntry.objects.create(
            provider="gemini", model_id="stub-embed",
            input_price_per_mtok=Decimal("1000000"),   # $1 per token
            output_price_per_mtok=Decimal("0"),
            price_source=CatalogueEntry.MANUAL,
        )
        for i in range(5):
            _document(f"doc{i}", retrievals=i)

        plan = reembed.plan(self.space, budget_usd=8.0)
        self.assertLess(plan.count, 5)
        self.assertGreater(plan.count, 0)
        self.assertLessEqual(plan.estimated_cost, 8.0)

    def test_an_unpriced_plan_says_so_rather_than_reporting_zero(self):
        _document("a")
        plan = reembed.plan(self.space)
        self.assertIsNone(plan.estimated_cost)
        self.assertIn("no price", plan.describe())

    def test_a_scope_filter_narrows_the_corpus(self):
        _document("mine", scope="editorial")
        _document("theirs", scope="chat")
        plan = reembed.plan(self.space, scope="editorial")
        self.assertEqual([d.title for d, _ in plan.documents], ["mine"])


class ExecuteTests(TestCase):

    def setUp(self):
        self.space, _ = reembed.target_space("gemini", "stub-embed", NARROW)
        self.memory = Memory(embedder=StubEmbedder())

    def test_it_embeds_the_planned_documents(self):
        _document("a")
        _document("b")
        report = reembed.execute(reembed.plan(self.space), memory=self.memory)
        self.assertEqual(report.embedded, 2)
        self.assertEqual(Embedding.objects.filter(space=self.space).count(), 2)

    def test_the_space_width_reaches_the_provider(self):
        """A query embedded at one width cannot be compared with vectors stored
        at another -- pgvector refuses outright."""
        embedder = StubEmbedder()
        _document("a")
        reembed.execute(reembed.plan(self.space), memory=Memory(embedder=embedder))
        self.assertEqual(embedder.widths, [NARROW])

    def test_a_batch_is_one_request_not_one_per_document(self):
        embedder = StubEmbedder()
        for i in range(5):
            _document(f"doc{i}")
        reembed.execute(
            reembed.plan(self.space), memory=Memory(embedder=embedder), batch_size=10,
        )
        self.assertEqual(len(embedder.batches), 1)

    def test_a_failed_batch_does_not_discard_the_ones_that_worked(self):
        class Flaky(StubEmbedder):
            def embed_documents(self, texts, output_dimensionality=None):
                if len(self.batches) == 1:
                    self.batches.append(list(texts))
                    raise RuntimeError("provider hiccup")
                return super().embed_documents(texts, output_dimensionality)

        for i in range(4):
            _document(f"doc{i}", retrievals=10 - i)

        report = reembed.execute(
            reembed.plan(self.space), memory=Memory(embedder=Flaky()), batch_size=2,
        )
        self.assertEqual(report.embedded, 2)
        self.assertEqual(report.failed, 2)
        self.assertTrue(report.errors)

    def test_re_running_picks_up_only_what_is_left(self):
        """Progress is 'which documents have a vector', so the job needs no
        state of its own to be resumable."""
        for i in range(4):
            _document(f"doc{i}", retrievals=10 - i)

        reembed.execute(
            reembed.plan(self.space, limit=2), memory=self.memory, batch_size=10,
        )
        second = reembed.plan(self.space)
        self.assertEqual(second.count, 2)

        reembed.execute(second, memory=self.memory)
        self.assertEqual(reembed.pending(self.space).count(), 0)

    def test_the_title_is_embedded_with_the_body(self):
        embedder = StubEmbedder()
        _document("A Distinctive Title")
        reembed.execute(reembed.plan(self.space), memory=Memory(embedder=embedder))
        self.assertIn("A Distinctive Title", embedder.batches[0][0])


class ActivationTests(TestCase):

    def setUp(self):
        # A partial unique index allows exactly one active space, and a kept
        # test database may already carry one from the backfill migration or
        # from an earlier module. Without this the suite passes or fails
        # depending on what ran before it.
        EmbeddingSpace.objects.filter(status=EmbeddingSpace.ACTIVE).update(
            status=EmbeddingSpace.RETIRED,
        )
        self.old = EmbeddingSpace.objects.create(
            provider="gemini", model_id="old", dimensions=NARROW,
            status=EmbeddingSpace.ACTIVE,
        )
        self.new, _ = reembed.target_space("gemini", "stub-embed", NARROW)

    def test_a_half_built_space_is_refused(self):
        """Activating one does not fail -- it silently returns worse results
        for the documents that happen to be missing."""
        _document("orphan")
        with self.assertRaises(ValueError) as caught:
            reembed.activate(self.new)
        self.assertIn("still have no vector", str(caught.exception))

    def test_cutover_retires_the_old_space_rather_than_deleting_it(self):
        reembed.activate(self.new, embedder=StubEmbedder())
        self.old.refresh_from_db()
        self.new.refresh_from_db()
        self.assertEqual(self.new.status, EmbeddingSpace.ACTIVE)
        self.assertEqual(self.old.status, EmbeddingSpace.RETIRED)
        # Still there, so a wrong cutover is reversed by flipping back.
        self.assertTrue(EmbeddingSpace.objects.filter(pk=self.old.pk).exists())

    def test_only_one_space_is_ever_active(self):
        reembed.activate(self.new, embedder=StubEmbedder())
        self.assertEqual(
            EmbeddingSpace.objects.filter(status=EmbeddingSpace.ACTIVE).count(), 1,
        )

    def test_force_no_longer_bypasses_complete_coverage(self):
        _document("orphan")
        with self.assertRaises(ValueError):
            reembed.activate(self.new, require_complete=False, embedder=StubEmbedder())
        self.assertEqual(EmbeddingSpace.active().pk, self.old.pk)

    def test_activation_records_when_it_happened(self):
        reembed.activate(self.new, embedder=StubEmbedder())
        self.new.refresh_from_db()
        self.assertIsNotNone(self.new.activated_at)


class IndexTests(TestCase):
    """The index itself, against a real Postgres.

    A plain TestCase, deliberately. CREATE INDEX CONCURRENTLY cannot run
    inside a transaction and a TestCase wraps every test in one -- but
    `ensure_index` already detects that and drops CONCURRENTLY, so the
    transaction is not an obstacle.

    TransactionTestCase would work too and is the wrong tool: it truncates
    every table on the way out, including the EmbeddingSpace the backfill
    migration created, which leaves a --keepdb database with no active space
    and fails roughly twenty tests in other modules that have nothing to do
    with indexes.
    """

    def test_a_space_within_the_limit_can_be_indexed(self):
        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=1536,
        )
        self.assertTrue(indexes.can_index(space))
        self.assertEqual(indexes.why_not(space), "")

    def test_the_space_that_prompted_this_cannot_be(self):
        """3072 is the native width of gemini-embedding-001 and pgvector caps
        hnsw at 2000. No amount of effort indexes it."""
        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=3072,
        )
        self.assertFalse(indexes.can_index(space))
        self.assertIn("exceeds pgvector's hnsw limit", indexes.why_not(space))

    def test_building_an_index_for_an_unindexable_space_is_not_an_error(self):
        """It still works, it just scans. A migration should not fail because
        the destination is merely slow."""
        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=3072,
        )
        self.assertIsNone(indexes.ensure_index(space))

    def test_an_index_is_created_and_found(self):
        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=64,
        )
        try:
            name = indexes.ensure_index(space)
            self.assertIsNotNone(name)
            self.assertTrue(indexes.index_exists(space))
            # Idempotent: a second run is a no-op, not a duplicate.
            self.assertEqual(indexes.ensure_index(space), name)
        finally:
            indexes.drop_index(space)

    def test_the_query_expression_matches_the_index_expression(self):
        """An expression index is only used by a query carrying the same
        expression. Written in one place and not the other, the index is built
        and never read."""
        from django.db.models.functions import Cast
        from pgvector.django import CosineDistance, VectorField

        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=64,
        )
        try:
            indexes.ensure_index(space)
            column = Memory._vector_column(space)
            self.assertIsInstance(column, Cast)

            sql, _ = (
                Embedding.objects.filter(space=space)
                .annotate(distance=CosineDistance(column, [0.0] * 64))
                .order_by("distance").query.sql_with_params()
            )
            self.assertIn("::vector(64)", sql)
        finally:
            indexes.drop_index(space)

    def test_an_unindexable_space_is_queried_without_a_pointless_cast(self):
        space = EmbeddingSpace.objects.create(
            provider="p", model_id="m", dimensions=3072,
        )
        self.assertEqual(Memory._vector_column(space), "vector")
