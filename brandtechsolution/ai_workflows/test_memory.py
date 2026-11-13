"""Step 2: the unified memory.

No provider is touched. The embedder is a stub that returns deterministic
vectors, because these tests are about what the *facade* does -- what it
stores, what provenance it records, what it counts -- and a live embedding
call would make every run measure something slightly different.
"""
import math

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from ai_workflows.harness.errors import MemoryUnavailable
from ai_workflows.harness.memory import Memory, content_hash
from ai_workflows.models import AgentProfile
from brand.models import BlogPost, Project
from knowledge_base.models import Embedding, EmbeddingSpace, MemoryDocument

DIMS = 3072


class StubEmbedder:
    """Deterministic vectors, so similarity is predictable.

    Each distinct text gets a unit vector along its own axis, which makes
    identical text score 1.0 against itself and unrelated text score 0.0 --
    enough to assert ordering without pretending to model semantics.
    """

    def __init__(self):
        self.calls = []
        self._axes = {}

    def _axis(self, text):
        return self._axes.setdefault(text, len(self._axes))

    def embed_query(self, text):
        self.calls.append(text)
        vector = [0.0] * DIMS
        vector[self._axis(text) % DIMS] = 1.0
        return vector


class MemoryTestCase(TestCase):
    def setUp(self):
        self.embedder = StubEmbedder()
        self.memory = Memory(embedder=self.embedder)
        # The backfill migration creates the active space, but a test database
        # built from migrations with no rows to carry has none.
        self.space, _ = EmbeddingSpace.objects.get_or_create(
            provider="gemini", model_id="models/gemini-embedding-001",
            dimensions=DIMS, defaults={"status": EmbeddingSpace.ACTIVE},
        )
        if self.space.status != EmbeddingSpace.ACTIVE:
            self.space.status = EmbeddingSpace.ACTIVE
            self.space.save()


class RememberTests(MemoryTestCase):
    def test_writing_embeds_without_being_asked(self):
        """There is no embed=True flag; the optional path is how vectors went stale."""
        self.memory.remember("agents coordinate through a message graph",
                             title="Orchestration", kind="note")

        self.assertEqual(Embedding.objects.count(), 1)
        self.assertEqual(len(self.embedder.calls), 1)

    def test_the_producing_model_is_recorded_on_the_vector(self):
        self.memory.remember("text", title="T")
        embedding = Embedding.objects.get()

        self.assertEqual(embedding.model_id, "models/gemini-embedding-001")
        self.assertEqual(embedding.provider, "gemini")
        self.assertEqual(embedding.dimensions, DIMS)

    def test_provenance_survives_the_space_being_corrected(self):
        """Denormalised on purpose: what produced a vector cannot change later."""
        self.memory.remember("text", title="T")
        # Ordinary saves now forbid identity edits. Simulate an external SQL
        # correction to retain coverage of denormalised historical provenance.
        EmbeddingSpace.objects.filter(pk=self.space.pk).update(model_id="renamed-after-the-fact")

        self.assertEqual(Embedding.objects.get().model_id, "models/gemini-embedding-001")

    def test_remembering_an_object_links_it(self):
        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        self.memory.remember("body", title="A post", kind="blog_post", obj=post)

        document = MemoryDocument.objects.get()
        self.assertEqual(document.object_id, post.pk)
        self.assertEqual(document.content_type, ContentType.objects.get_for_model(BlogPost))

    def test_unchanged_text_is_not_re_embedded(self):
        """A repeated save must be free, not another paid call."""
        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        self.memory.remember("body", title="A post", obj=post)
        self.memory.remember("body", title="A post", obj=post)

        self.assertEqual(len(self.embedder.calls), 1)
        self.assertEqual(Embedding.objects.count(), 1)

    def test_changed_text_is_re_embedded_in_place(self):
        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        self.memory.remember("body", title="A post", obj=post)
        self.memory.remember("a different body", title="A post", obj=post)

        self.assertEqual(len(self.embedder.calls), 2)
        # One document, one vector -- updated, not duplicated.
        self.assertEqual(MemoryDocument.objects.count(), 1)
        self.assertEqual(Embedding.objects.count(), 1)
        self.assertEqual(MemoryDocument.objects.get().content_hash,
                         content_hash("a different body"))

    def test_without_an_active_space_it_refuses_rather_than_guessing(self):
        EmbeddingSpace.objects.update(status=EmbeddingSpace.RETIRED)
        with self.assertRaises(MemoryUnavailable):
            self.memory.remember("text", title="T")

    def test_an_embedder_failure_surfaces_as_memory_unavailable(self):
        class Broken:
            def embed_query(self, text):
                raise RuntimeError("provider down")

        with self.assertRaises(MemoryUnavailable):
            Memory(embedder=Broken()).remember("text", title="T")


class RecallTests(MemoryTestCase):
    def setUp(self):
        super().setUp()
        self.memory.remember("multi-agent orchestration", title="Orchestration", kind="note")
        self.memory.remember("kubernetes autoscaling", title="Scaling", kind="note")
        self.memory.remember("an unrelated recipe", title="Recipe", kind="other")

    def test_the_closest_document_comes_first(self):
        results = self.memory.recall("multi-agent orchestration")
        self.assertEqual(results[0].title, "Orchestration")
        self.assertAlmostEqual(results[0].score, 1.0, places=5)

    def test_results_carry_the_model_that_produced_them(self):
        result = self.memory.recall("multi-agent orchestration")[0]
        self.assertEqual(result.model_id, "models/gemini-embedding-001")

    def test_recall_can_be_limited_by_kind(self):
        results = self.memory.recall("anything", kind="other")
        self.assertEqual({r.title for r in results}, {"Recipe"})

    def test_the_limit_is_respected(self):
        self.assertEqual(len(self.memory.recall("anything", limit=2)), 2)

    def test_retrieval_is_counted(self):
        """The importance signal that did not exist before."""
        self.memory.recall("multi-agent orchestration", limit=1)
        document = MemoryDocument.objects.get(title="Orchestration")

        self.assertEqual(document.retrieval_count, 1)
        self.assertIsNotNone(document.last_retrieved_at)

    def test_counting_accumulates_across_recalls(self):
        for _ in range(3):
            self.memory.recall("multi-agent orchestration", limit=1)
        self.assertEqual(MemoryDocument.objects.get(title="Orchestration").retrieval_count, 3)

    def test_counting_can_be_suppressed(self):
        """A re-embed sweep reading its own store must not inflate the signal."""
        self.memory.recall("multi-agent orchestration", limit=1, record_usage=False)
        self.assertEqual(MemoryDocument.objects.get(title="Orchestration").retrieval_count, 0)

    def test_only_the_active_space_is_searched(self):
        """A half-built space must never leak into results."""
        building = EmbeddingSpace.objects.create(
            provider="other", model_id="other-embed", dimensions=DIMS,
            status=EmbeddingSpace.BUILDING,
        )
        document = MemoryDocument.objects.create(kind="note", title="Only in the new space",
                                                 text="x")
        Embedding.objects.create(
            space=building, document=document, provider="other",
            model_id="other-embed", dimensions=DIMS, vector=[1.0] * DIMS,
        )

        titles = {r.title for r in self.memory.recall("anything", limit=10)}
        self.assertNotIn("Only in the new space", titles)


class SpaceTests(MemoryTestCase):
    def test_two_active_spaces_are_refused_by_the_database(self):
        """Two active spaces would mean queries silently drawing from both."""
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmbeddingSpace.objects.create(
                provider="other", model_id="other", dimensions=DIMS,
                status=EmbeddingSpace.ACTIVE,
            )

    def test_a_document_has_at_most_one_vector_per_space(self):
        from django.db import IntegrityError, transaction

        document = MemoryDocument.objects.create(kind="note", title="T", text="x")
        Embedding.objects.create(space=self.space, document=document, provider="gemini",
                                 model_id="m", dimensions=DIMS, vector=[0.0] * DIMS)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Embedding.objects.create(space=self.space, document=document, provider="gemini",
                                     model_id="m", dimensions=DIMS, vector=[1.0] * DIMS)

    def test_a_space_can_hold_vectors_of_its_own_width(self):
        """The column is unconstrained, so two spaces can coexist mid-migration."""
        narrow = EmbeddingSpace.objects.create(
            provider="other", model_id="small-embed", dimensions=8,
            status=EmbeddingSpace.BUILDING,
        )
        document = MemoryDocument.objects.create(kind="note", title="T", text="x")
        Embedding.objects.create(space=narrow, document=document, provider="other",
                                 model_id="small-embed", dimensions=8, vector=[0.5] * 8)

        self.assertEqual(len(Embedding.objects.get(space=narrow).vector), 8)


class ForgetTests(MemoryTestCase):
    def test_forgetting_an_object_removes_its_vector_too(self):
        project = Project.objects.create(title="P", description="d")
        self.memory.remember("d", title="P", kind="project", obj=project)

        self.memory.forget(project)
        self.assertEqual(MemoryDocument.objects.count(), 0)
        self.assertEqual(Embedding.objects.count(), 0)


class ProfileTests(TestCase):
    def test_load_always_returns_the_same_row(self):
        first = AgentProfile.load()
        second = AgentProfile.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AgentProfile.objects.count(), 1)

    def test_a_second_profile_cannot_be_created(self):
        """A second row would reintroduce the ambiguity this replaces.

        The guarantee is enforced by the primary key, so the attempt raises
        rather than quietly succeeding and leaving two brand voices to drift
        apart -- which is the exact failure being designed out.
        """
        from django.db import IntegrityError, transaction

        AgentProfile.load()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentProfile.objects.create(brand_voice="a rival voice")

    def test_saving_an_edit_updates_the_one_row(self):
        profile = AgentProfile.load()
        profile.brand_voice = "Terse and factual."
        profile.save()

        self.assertEqual(AgentProfile.objects.count(), 1)
        self.assertEqual(AgentProfile.load().brand_voice, "Terse and factual.")

    def test_it_carries_the_brand_voice_every_agent_shares(self):
        profile = AgentProfile.load()
        self.assertTrue(profile.brand_voice)

    def test_it_is_reachable_from_the_facade(self):
        self.assertEqual(Memory(embedder=StubEmbedder()).profile().pk,
                         AgentProfile.SINGLETON_ID)


class EpisodicTests(TestCase):
    def test_a_thread_checkpointer_is_reachable_from_the_facade(self):
        from ai_workflows.checkpointer import DjangoCheckpointer

        checkpointer = Memory(embedder=StubEmbedder()).thread("thread-1")
        self.assertIsInstance(checkpointer, DjangoCheckpointer)


class BackfillTests(TestCase):
    """What the migration produced, asserted against the schema it produced it in."""

    def test_the_legacy_space_is_the_active_one(self):
        space = EmbeddingSpace.active()
        self.assertIsNotNone(space)
        self.assertEqual(space.dimensions, DIMS)

    def test_the_vector_column_accepts_the_legacy_width(self):
        space = EmbeddingSpace.active()
        document = MemoryDocument.objects.create(kind="note", title="T", text="x")
        embedding = Embedding.objects.create(
            space=space, document=document, provider=space.provider,
            model_id=space.model_id, dimensions=space.dimensions,
            vector=[1.0 / math.sqrt(DIMS)] * DIMS,
        )
        self.assertEqual(len(embedding.vector), DIMS)


class IndexingTests(MemoryTestCase):
    """Vectorise-on-write: the gap that made every stored vector stale."""

    def setUp(self):
        super().setUp()
        from unittest.mock import patch

        self.queued = []
        patcher = patch(
            "ai_workflows.tasks.embed_object_task.delay",
            side_effect=lambda *a, **k: self.queued.append(a),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _index(self, obj, **kwargs):
        from ai_workflows.harness.indexing import index_on_save

        # on_commit callbacks do not fire inside a test transaction unless
        # captured, which is the whole point of the hook being on_commit.
        with self.captureOnCommitCallbacks(execute=True):
            return index_on_save(obj, **kwargs)

    def test_a_new_object_is_queued_for_embedding(self):
        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        queued = self._index(post, kind="blog_post", text_field="content")

        self.assertTrue(queued)
        self.assertEqual(len(self.queued), 1)
        self.assertEqual(self.queued[0][:3], ("brand", "blogpost", post.pk))

    def test_an_unchanged_save_does_not_queue_work(self):
        """Publishing a post or toggling `featured` must not cost an embedding."""
        from ai_workflows.harness.indexing import text_for

        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        # The text production would have stored, not the bare content field:
        # indexing embeds `get_embedding_text()`, which folds in the title,
        # category and tags, and a stored hash of anything else would make
        # every save look like an edit.
        self.memory.remember(text_for(post), title="A post", kind="blog_post",
                             obj=post)

        queued = self._index(post, kind="blog_post", text_field="content")
        self.assertFalse(queued)
        self.assertEqual(self.queued, [])

    def test_an_edit_queues_a_re_embedding(self):
        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")
        self.memory.remember("body", title="A post", kind="blog_post", obj=post)

        post.content = "a materially different body"
        post.save()
        queued = self._index(post, kind="blog_post", text_field="content")

        self.assertTrue(queued)
        self.assertEqual(len(self.queued), 1)

    def test_the_task_embeds_and_is_safe_to_replay(self):
        """Replaying must not duplicate the vector or pay for it twice.

        The task builds its own Memory(), which resolves the embedder through
        llm.get_embedder -- so stubbing that exercises the real resolution path
        rather than substituting the facade wholesale.
        """
        from unittest.mock import patch

        from ai_workflows.tasks import embed_object_task

        post = BlogPost.objects.create(title="A post", excerpt="e", content="body")

        with patch("ai_workflows.harness.llm.get_embedder", return_value=self.embedder):
            embed_object_task.run("brand", "blogpost", post.pk, "blog_post", "A post", "body")
            embed_object_task.run("brand", "blogpost", post.pk, "blog_post", "A post", "body")

        self.assertEqual(Embedding.objects.count(), 1)
        self.assertEqual(len(self.embedder.calls), 1)

    def test_a_deleted_row_is_not_retried(self):
        from ai_workflows.tasks import embed_object_task

        result = embed_object_task.run("brand", "blogpost", 999999, "blog_post", "T", "x")
        self.assertEqual(result["status"], "missing")


class ScopeTests(TestCase):
    """`Memory(scope=...)` was accepted, stored, and ignored.

    Every caller that thought it was scoping its reads was reading everything.
    These are about it being true.
    """

    def setUp(self):
        from editorial.tests.fakes import FakeEmbedder

        self.embedder = FakeEmbedder()
        self.editorial = Memory(embedder=self.embedder, scope="editorial")
        self.site = Memory(embedder=self.embedder, scope="site")

        self.editorial.remember("Agents coordinate through a message graph.",
                                title="An article", kind="article")
        self.site.remember("Agents coordinate through a message graph.",
                           title="A blog post", kind="blog")

    def test_a_document_records_the_scope_it_was_written_in(self):
        from knowledge_base.models import MemoryDocument

        self.assertEqual(
            MemoryDocument.objects.get(title="An article").scope, "editorial"
        )

    def test_recall_sees_only_its_own_scope_by_default(self):
        titles = [r.title for r in self.editorial.recall("agents")]
        self.assertEqual(titles, ["An article"])

    def test_the_other_scope_sees_the_other_document(self):
        titles = [r.title for r in self.site.recall("agents")]
        self.assertEqual(titles, ["A blog post"])

    def test_several_scopes_can_be_read_at_once(self):
        """Merging scopes is sound in a way merging spaces is not: the vectors
        are comparable, so this is a choice about what the caller should see."""
        titles = {
            r.title for r in
            self.editorial.recall("agents", scope=("editorial", "site"))
        }
        self.assertEqual(titles, {"An article", "A blog post"})

    def test_everything_requires_saying_so(self):
        titles = {r.title for r in self.editorial.recall("agents", scope=None)}
        self.assertEqual(titles, {"An article", "A blog post"})

    def test_an_unused_scope_finds_nothing(self):
        other = Memory(embedder=self.embedder, scope="nowhere")
        self.assertEqual(other.recall("agents"), [])

    def test_the_default_scope_is_still_the_default(self):
        plain = Memory(embedder=self.embedder)
        plain.remember("Something else entirely.", title="Unscoped")

        self.assertEqual([r.title for r in plain.recall("something")], ["Unscoped"])
