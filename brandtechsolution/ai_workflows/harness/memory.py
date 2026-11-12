"""One memory, three layers.

Memory was in three places that did not know about each other: a checkpointer
used only by chat, a singleton row of brand guidelines used only by editorial,
and a pgvector store that was barely used at all -- while the newsroom's
duplicate-coverage check compared the first twenty characters of a title.

The layers stay separate because they answer genuinely different questions:

- **episodic** -- what happened in this thread? (`DjangoCheckpointer`)
- **semantic** -- what do we already know about X? (pgvector)
- **profile**  -- how do we speak, and what do we avoid? (`AgentProfile`)

Writing to semantic memory embeds it. There is no `embed=True` flag, because
an optional embedding is precisely how the current stores drifted apart.
"""
import hashlib
import inspect
import logging
import math

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from ai_workflows.harness.errors import MemoryUnavailable

logger = logging.getLogger(__name__)


# The default for `recall(scope=...)`, so that "this memory's own scope" and
# "every scope" are different things and neither is spelled None by accident.
OWN_SCOPE = object()


def _as_scopes(scope):
    return [scope] if isinstance(scope, str) else list(scope)


def content_hash(text) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class MemoryRecord:
    """One recalled document, with its score and where the vector came from."""

    def __init__(self, document, score=None, model_id="", provider=""):
        self.document = document
        self.score = score
        self.model_id = model_id
        self.provider = provider

    @property
    def title(self):
        return self.document.title

    @property
    def text(self):
        return self.document.text

    def __repr__(self):
        return f"<MemoryRecord {self.document.title[:40]!r} score={self.score}>"


class Memory:
    """The facade every agent uses.

    `embedder` is injected so tests do not need a provider and so the
    embedding client is a dependency rather than a hidden import. It is
    resolved lazily: constructing a Memory must not require a working API key,
    or importing an agent would.
    """

    def __init__(self, embedder=None, scope="default"):
        self._embedder = embedder
        self._embedder_resolved = embedder is not None

        # What this memory writes to, and what it reads from unless a caller
        # says otherwise. Two agents with different scopes do not see each
        # other's documents, which is the difference between the newsroom
        # searching its own back catalogue and the newsroom searching every
        # chat transcript the assistant ever saved.
        self.scope = scope

    # ------------------------------------------------------------------
    # semantic
    # ------------------------------------------------------------------

    @property
    def embedder(self):
        if not self._embedder_resolved:
            from ai_workflows.harness.llm import get_embedder

            self._embedder = get_embedder()
            self._embedder_resolved = True
        return self._embedder

    def _active_space(self):
        from knowledge_base.models import EmbeddingSpace

        space = EmbeddingSpace.active()
        if space is None:
            raise MemoryUnavailable(
                "no active embedding space; run the backfill migration or "
                "activate a space before using semantic memory"
            )
        return space

    def remember(self, text, *, title="", kind="document", obj=None, metadata=None):
        """Store `text` and embed it.

        Embedding on write, not on request: the optional path is how
        `BlogPost.embedding` came to be written only by a management command
        and went stale from the first edit onwards.

        Unchanged text is not re-embedded. The content hash makes a repeated
        save free rather than another paid call.
        """
        from knowledge_base.models import Embedding, MemoryDocument

        space = self._active_space()
        digest = content_hash(text)

        lookup = {"content_type": None, "object_id": None}
        if obj is not None:
            lookup = {
                "content_type": ContentType.objects.get_for_model(obj.__class__),
                "object_id": obj.pk,
            }

        with transaction.atomic():
            if obj is not None:
                document, _ = MemoryDocument.objects.get_or_create(
                    **lookup,
                    defaults={"scope": self.scope, "kind": kind,
                              "title": title[:300], "text": text,
                              "metadata": metadata or {}, "content_hash": digest},
                )
            else:
                document = MemoryDocument.objects.create(
                    scope=self.scope, kind=kind, title=title[:300], text=text,
                    metadata=metadata or {}, content_hash=digest,
                )

            already = Embedding.objects.filter(space=space, document=document).exists()
            if already and document.content_hash == digest:
                return MemoryRecord(document)

            document.title = title[:300] or document.title
            document.text = text
            document.content_hash = digest
            if metadata:
                document.metadata = metadata
            document.save()

        vector = self._embed(text, space)

        Embedding.objects.update_or_create(
            space=space, document=document,
            defaults={
                "provider": space.provider,
                "model_id": space.model_id,
                "dimensions": space.dimensions,
                "vector": vector,
            },
        )
        return MemoryRecord(document, model_id=space.model_id, provider=space.provider)

    def recall(self, query, *, kind=None, limit=5, record_usage=True,
               scope=OWN_SCOPE):
        """The most similar documents in the active space.

        Only ever the active space. A half-built space must not leak into
        results, and merging scores across two spaces is unsound -- they share
        no scale, so the merge would be arbitrary.

        Scoped to this memory's own corpus by default. A caller that genuinely
        wants everything passes `scope=None` and has to mean it; one that wants
        several passes a list. Merging *scopes* is sound in a way merging spaces
        is not -- the vectors are comparable -- so this is a choice about what
        the caller should see, not about whether the numbers mean anything.

        Retrieval is counted here because this is the one chokepoint every
        semantic lookup passes through. After a few weeks that counter says
        which documents matter far better than view counts do, because it
        measures what the agents use rather than what humans clicked -- and it
        is the input to deciding what gets re-embedded first when the model
        changes.
        """
        from pgvector.django import CosineDistance

        from knowledge_base.models import Embedding, MemoryDocument

        space = self._active_space()
        vector = self._embed(query, space)

        rows = (
            Embedding.objects.filter(space=space)
            .select_related("document")
            .annotate(distance=CosineDistance(self._vector_column(space), vector))
            .order_by("distance")
        )

        if scope is OWN_SCOPE:
            scope = self.scope
        if scope is not None:
            rows = rows.filter(document__scope__in=_as_scopes(scope))
        # Generic memory has no authenticated ACL context. Explicit scope names
        # must not provide a bypass; library retrieval uses its own joined query.
        from knowledge_base.library.retrieval import PROTECTED_LIBRARY_SCOPES
        rows = rows.exclude(document__scope__in=PROTECTED_LIBRARY_SCOPES)

        if kind:
            rows = rows.filter(document__kind=kind)

        results = list(rows[:limit])

        if record_usage and results:
            self._record_usage([r.document_id for r in results])

        return [
            MemoryRecord(
                row.document,
                score=1.0 - float(row.distance),
                model_id=row.model_id,
                provider=row.provider,
            )
            for row in results
        ]

    @staticmethod
    def _record_usage(document_ids):
        """Count a retrieval without racing other workers.

        An F() update rather than read-modify-write: two workers recalling the
        same document concurrently would otherwise each read the same count and
        write the same increment, losing one.
        """
        from django.db.models import F

        from knowledge_base.models import MemoryDocument

        MemoryDocument.objects.filter(id__in=document_ids).update(
            retrieval_count=F("retrieval_count") + 1,
            last_retrieved_at=timezone.now(),
        )

    @staticmethod
    def _vector_column(space):
        """The expression to compare against, cast when an index expects it.

        `Embedding.vector` is a bare `vector` column with no declared width, so
        Postgres will not index it -- "column does not have dimensions". The
        index is built over `vector::vector(N)` instead, and an expression
        index is only used by a query carrying the *same* expression. So the
        cast has to be here as well as there; written in one place and not the
        other, the index is built and never read.

        Left uncast for a space too wide to index, where the cast would be
        pure overhead. See `knowledge_base/indexes.py`.
        """
        from django.db.models.functions import Cast
        from pgvector.django import VectorField

        from knowledge_base.indexes import can_index

        if not can_index(space):
            return "vector"
        return Cast("vector", VectorField(dimensions=space.dimensions))

    @staticmethod
    def _normalise(vector):
        """Scale a vector to unit length.

        Cosine distance is scale-invariant, so this changes no ranking today.
        It is here because `gemini-embedding-001` returns unit vectors only at
        its native 3072 width -- a narrower space asks for a Matryoshka
        truncation, and those come back unnormalised. Storing both kinds side
        by side would mean scores that are comparable within a space and
        quietly not comparable in magnitude across the migration, and it would
        block ever using the cheaper inner-product opclass.
        """
        length = math.sqrt(sum(value * value for value in vector))
        if not length:
            return vector
        return [value / length for value in vector]

    def _embed(self, text, space=None):
        """Embed `text` at the width the space expects.

        The width is not optional. A query embedded at 3072 dimensions cannot
        be compared with vectors stored at 1536 -- pgvector refuses outright --
        so a space's width has to reach every call that touches it, not just
        the ones that write.
        """
        try:
            vector = self._embed_call(
                self.embedder.embed_query, text or "", space,
            )
        except MemoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MemoryUnavailable(f"could not embed: {exc}") from exc

        return self._normalise(vector)

    def embed_many(self, texts, space):
        """Embed a batch, for the re-embedding job.

        One request for many documents rather than one each: the provider
        charges the same for the tokens and the round trips dominate a backfill
        of any size.
        """
        try:
            vectors = self._embed_call(
                self.embedder.embed_documents, list(texts), space,
            )
        except Exception as exc:  # noqa: BLE001
            raise MemoryUnavailable(f"could not embed a batch: {exc}") from exc

        return [self._normalise(vector) for vector in vectors]

    @staticmethod
    def _embed_call(method, payload, space):
        """Call an embedder, passing the width only if it can take one.

        Not every embedder accepts `output_dimensionality` -- the test doubles
        do not, and neither would another provider's client. Asked by
        signature rather than discovered by catching TypeError, which would
        also swallow a genuine TypeError raised inside the call.
        """
        dimensions = getattr(space, "dimensions", None)
        if dimensions:
            try:
                accepts = "output_dimensionality" in inspect.signature(method).parameters
            except (TypeError, ValueError):
                accepts = False
            if accepts:
                return method(payload, output_dimensionality=dimensions)
        return method(payload)

    def forget(self, obj):
        """Drop what is remembered about `obj`."""
        from knowledge_base.models import MemoryDocument

        return MemoryDocument.objects.filter(
            content_type=ContentType.objects.get_for_model(obj.__class__),
            object_id=obj.pk,
        ).delete()[0]

    # ------------------------------------------------------------------
    # episodic
    # ------------------------------------------------------------------

    def thread(self, thread_id):
        """The checkpointer for one conversation.

        Unchanged from what the chat assistant already uses -- it was the
        best-built piece of the three stores. It is reachable from here so that
        every agent has one way in.
        """
        from ai_workflows.checkpointer import DjangoCheckpointer

        return DjangoCheckpointer(thread_id)

    # ------------------------------------------------------------------
    # profile
    # ------------------------------------------------------------------

    def profile(self):
        from ai_workflows.models import AgentProfile

        return AgentProfile.load()
