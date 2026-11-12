"""Unit and integration tests for Library Retrieval Engine and Memory Isolation.

Verifies:
- Internal vs Public retrieval isolation
- Prevention of generic unscoped memory leakage (scope=None)
- Tamper-safe citation formatting with page/section provenance
- Immediate synchronous exclusion upon document deletion or revocation
"""

from django.test import TestCase

from ai_workflows.harness.memory import Memory
from knowledge_base.library.contracts import (
    Audience,
    DocumentVisibility,
    PublicApprovalState,
)
from knowledge_base.library.retrieval import (
    PROTECTED_LIBRARY_SCOPES,
    LibraryRetrievalEngine,
)
from knowledge_base.library.stubs import create_test_scenarios
from knowledge_base.models import Embedding, EmbeddingSpace, MemoryDocument


class StubEmbedder:
    """Deterministic embedding stub returning unit vectors."""
    def __init__(self, dims=3072):
        self.dims = dims
        self._axes = {}

    def _axis(self, text):
        return self._axes.setdefault(text, len(self._axes))

    def embed_query(self, text):
        vec = [0.0] * self.dims
        vec[self._axis(text) % self.dims] = 1.0
        return vec


class LibraryRetrievalTests(TestCase):
    def setUp(self):
        self.scenarios = create_test_scenarios()
        self.store = self.scenarios["store"]
        self.actors = self.scenarios["actors"]
        self.docs = self.scenarios["docs"]
        self.versions = self.scenarios["versions"]
        self.engine = LibraryRetrievalEngine(store=self.store)

    def test_internal_retrieval_returns_only_authorized_documents(self):
        """Internal retrieval must only return chunks the specific actor holds grants for."""
        reader = self.actors["reader_user"]
        colleague = self.actors["org_staff"]

        # Reader has explicit grant for 'arch-spec.pdf' (API Architecture Design Document)
        reader_results = self.engine.retrieve(
            query="API architecture JSON-RPC",
            actor=reader,
            audience=Audience.INTERNAL,
        )
        returned_titles = {r.title for r in reader_results}
        self.assertIn("API Architecture Design Document", returned_titles)
        # Reader has NO grant for private strategy notes or lab report
        self.assertNotIn("2026 Strategic Advisory Notes", returned_titles)
        self.assertNotIn("Biometric Lab Research Findings", returned_titles)

        # Colleague is staff, so they see organisation documents (Employee Handbook)
        colleague_results = self.engine.retrieve(
            query="employee ethics handbook",
            actor=colleague,
            audience=Audience.INTERNAL,
        )
        colleague_titles = {r.title for r in colleague_results}
        self.assertIn("Employee Handbook and Code of Conduct", colleague_titles)
        self.assertNotIn("API Architecture Design Document", colleague_titles)

    def test_public_retrieval_returns_only_approved_public_documents(self):
        """Public retrieval must only surface documents with current-version approval."""
        anonymous = self.actors["anonymous"]

        public_results = self.engine.retrieve(
            query="AI governance enterprise",
            actor=anonymous,
            audience=Audience.PUBLIC,
        )
        returned_titles = {r.title for r in public_results}
        self.assertEqual(returned_titles, {"Teklora Public Whitepaper on AI Governance"})

        # Assert citations have safe format
        first = public_results[0]
        self.assertEqual(
            first.citation,
            f"[Doc #{first.document_id} v1: Teklora Public Whitepaper on AI Governance, Executive Summary]",
        )
        self.assertTrue(first.is_public)

    def test_public_retrieval_excludes_revoked_and_deleted_documents(self):
        """Revocation or deletion immediately removes chunks from public results."""
        anonymous = self.actors["anonymous"]

        results = self.engine.retrieve(
            query="announcement retracted specification obsolete",
            actor=anonymous,
            audience=Audience.PUBLIC,
        )
        returned_titles = {r.title for r in results}
        self.assertNotIn("Deprecated Press Release 2025", returned_titles)
        self.assertNotIn("Obsolete Scrapped Specification", returned_titles)


class MemoryIsolationTests(TestCase):
    """Test that generic memory recall (scope=None) does not leak library records."""

    def setUp(self):
        self.embedder = StubEmbedder()
        self.memory = Memory(embedder=self.embedder)
        self.space, _ = EmbeddingSpace.objects.get_or_create(
            provider="gemini",
            model_id="models/gemini-embedding-001",
            dimensions=3072,
            defaults={"status": EmbeddingSpace.ACTIVE},
        )
        if self.space.status != EmbeddingSpace.ACTIVE:
            self.space.status = EmbeddingSpace.ACTIVE
            self.space.save()

    def test_generic_unscoped_recall_excludes_protected_library_records(self):
        """Memory.recall(scope=None) must NOT leak protected library documents."""
        # 1. Normal editorial document
        editorial_mem = Memory(embedder=self.embedder, scope="editorial")
        editorial_mem.remember(
            "An editorial article on technology and innovation.",
            title="Public Editorial Article",
        )

        # 2. Protected library document chunk
        lib_memory = Memory(embedder=self.embedder, scope="library")
        lib_memory.remember(
            "Confidential board minutes regarding proprietary M&A strategy.",
            title="Confidential Board Minutes",
        )

        # Query generic unscoped memory: scope=None
        unscoped_results = self.memory.recall("Confidential board minutes article", scope=None)
        unscoped_titles = {r.title for r in unscoped_results}

        # The editorial article is visible, but the protected library document is excluded
        self.assertIn("Public Editorial Article", unscoped_titles)
        self.assertNotIn("Confidential Board Minutes", unscoped_titles)

    def test_explicit_scope_cannot_bypass_library_authorization(self):
        """A scope name is not an authorization context; use the ACL retrieval service."""
        lib_memory = Memory(embedder=self.embedder, scope="library")
        lib_memory.remember(
            "Private research paper on quantum computing benchmarks.",
            title="Quantum Research Paper",
        )

        scoped_results = lib_memory.recall("Quantum computing benchmarks")
        scoped_titles = {r.title for r in scoped_results}
        self.assertNotIn("Quantum Research Paper", scoped_titles)
        self.assertEqual(lib_memory.recall('quantum', scope=('library', 'staff_library')), [])
