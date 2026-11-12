"""Step 4: the tool registry and per-agent suites.

The move was exactly a move: the assistant kept the same three tools, in the
same order, with the user info tool still bound per call and still absent for
an anonymous caller.

Step 7 added `current_time` and step 9 added `search_knowledge` and
`fetch_url`. The counts here are pinned so that adding a tool stays a
deliberate act with a suite placement, rather than something that happens to an
agent nobody was thinking about -- which has now worked three times, most
recently by catching step 9 shipping without this file updated.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from ai_workflows.harness.errors import ToolFailed
from ai_workflows.harness.tools import (
    SUITES,
    ToolContext,
    ToolRegistry,
    register_builtin_tools,
    suite_for,
)


def _fake_tool(name):
    """Something tool-shaped, without importing the retrievers."""
    return type("FakeTool", (), {"name": name, "__repr__": lambda s: f"<tool {name}>"})()


class RegistryTests(TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_a_static_tool_resolves(self):
        tool = self.registry.register("search", _fake_tool("search"))
        self.assertEqual(self.registry.resolve(["search"]), [tool])

    def test_a_bound_tool_is_built_from_the_context(self):
        seen = {}

        def factory(ctx):
            seen["user_id"] = ctx.user_id
            return _fake_tool("user_info")

        self.registry.register_factory("user_info", factory)
        resolved = self.registry.resolve(["user_info"], ToolContext(user_id=7))

        self.assertEqual(len(resolved), 1)
        self.assertEqual(seen["user_id"], 7)

    def test_a_factory_returning_none_omits_the_tool(self):
        """An anonymous caller has no user to describe; an always-failing tool
        is worse than an absent one."""
        self.registry.register_factory("user_info", lambda ctx: None)
        self.assertEqual(self.registry.resolve(["user_info"], ToolContext()), [])

    def test_an_unknown_tool_raises_rather_than_being_skipped(self):
        """A suite naming a tool that does not exist is a typo.

        Skipping it would surface much later as the model mysteriously
        declining to look something up.
        """
        with self.assertRaises(ToolFailed) as caught:
            self.registry.resolve(["nope"])
        self.assertIn("nope", str(caught.exception))

    def test_the_error_lists_what_is_registered(self):
        self.registry.register("search", _fake_tool("search"))
        with self.assertRaises(ToolFailed) as caught:
            self.registry.resolve(["typo"])
        self.assertIn("search", str(caught.exception))

    def test_a_duplicate_registration_is_refused(self):
        self.registry.register("search", _fake_tool("search"))
        with self.assertRaises(ValueError):
            self.registry.register("search", _fake_tool("other"))

    def test_a_name_cannot_be_both_static_and_bound(self):
        self.registry.register("search", _fake_tool("search"))
        with self.assertRaises(ValueError):
            self.registry.register_factory("search", lambda ctx: None)

    def test_order_follows_the_suite_not_the_registry(self):
        self.registry.register("b", _fake_tool("b"))
        self.registry.register("a", _fake_tool("a"))
        resolved = self.registry.resolve(["a", "b"])
        self.assertEqual([t.name for t in resolved], ["a", "b"])


class SuiteTests(TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        for name in ("search_blog_posts", "search_projects", "current_time", "search_public_library"):
            self.registry.register(name, _fake_tool(name))
        self.registry.register_factory(
            "user_info", lambda ctx: _fake_tool("user_info") if ctx.user_id else None
        )

    def test_the_assistant_gets_its_five_tools(self):
        resolved = suite_for("assistant", ToolContext(user_id=1), registry=self.registry)
        self.assertEqual(
            [t.name for t in resolved],
            ["search_blog_posts", "search_projects", "user_info", "current_time", "search_public_library"],
        )

    def test_an_anonymous_assistant_gets_four(self):
        """Public library access adds no user tool or private document access."""
        resolved = suite_for("assistant", ToolContext(), registry=self.registry)
        self.assertEqual([t.name for t in resolved],
                         ["search_blog_posts", "search_projects", "current_time", "search_public_library"])

    def test_an_agent_with_no_suite_gets_nothing_rather_than_everything(self):
        """Defaulting to every tool would quietly hand each new tool to agents
        nobody considered when adding it."""
        self.assertEqual(suite_for("unlisted", registry=self.registry), [])

    def test_every_agent_has_a_declared_suite_even_an_empty_one(self):
        """Step 4's concern, which outlived the empty suites themselves.

        These were all `[]` until step 9 gave the newsroom real tools -- the
        assertion that they were empty has moved to
        `test_newsroom_tools.SuiteTests`, where the question is who got what.
        What survives here is the rule that made that reviewable: a suite is
        declared for every agent, so a gap reads as a decision rather than as
        an oversight.
        """
        for agent in ("trend_intelligence", "trend_prediction", "research",
                      "fact_verifier", "writer", "social", "newsroom"):
            self.assertIn(agent, SUITES, f"{agent} has no declared suite")

    def test_every_suite_names_only_registered_tools(self):
        """Guards against a suite drifting ahead of the registry."""
        registry = register_builtin_tools(ToolRegistry())
        for agent, names in SUITES.items():
            for name in names:
                self.assertIn(name, registry, f"{agent} names an unregistered tool")


class BuiltinRegistrationTests(TestCase):
    BUILTINS = [
        "current_time", "fetch_url", "search_blog_posts", "search_knowledge",
        "search_projects", "search_public_library", "user_info",
    ]

    def test_every_builtin_tool_registers(self):
        registry = register_builtin_tools(ToolRegistry())
        self.assertEqual(registry.names(), self.BUILTINS)

    def test_registering_twice_is_harmless(self):
        """It is called on every ChatAssistant construction."""
        registry = ToolRegistry()
        register_builtin_tools(registry)
        register_builtin_tools(registry)
        self.assertEqual(len(registry.names()), len(self.BUILTINS))

    def test_the_clock_tool_answers_without_a_caller(self):
        """Static for every user, so it is registered rather than bound."""
        registry = register_builtin_tools(ToolRegistry())
        answer = registry.resolve(["current_time"])[0].invoke({})
        self.assertIn("UTC", answer)
        self.assertIn("EAT", answer)

    def test_the_user_info_tool_is_bound_to_the_caller(self):
        user = User.objects.create_user("someone", email="a@example.com")
        registry = register_builtin_tools(ToolRegistry())

        resolved = registry.resolve(["user_info"], ToolContext(user_id=user.pk))
        self.assertEqual(len(resolved), 1)
        self.assertIn("someone", resolved[0].invoke({}))

    def test_an_anonymous_caller_gets_no_user_tool(self):
        registry = register_builtin_tools(ToolRegistry())
        self.assertEqual(registry.resolve(["user_info"], ToolContext()), [])


class AssistantWiringTests(TestCase):
    """The assistant receives public references, never private library tools."""

    def _assistant(self, **kwargs):
        from ai_workflows.service import ChatAssistant

        # The constructor resolves a real model; the tools are what is under
        # test, so resolution and the graph are both stubbed. Since step 7 the
        # model comes from the harness, so this patches one seam rather than
        # naming a vendor class.
        with patch("ai_workflows.service.iter_models"), \
                patch("ai_workflows.service.create_react_agent"):
            return ChatAssistant(thread_id="t-1", **kwargs)

    def test_an_authenticated_assistant_gets_five_tools(self):
        user = User.objects.create_user("someone", email="a@example.com")
        self.assertEqual(len(self._assistant(user_id=user.pk).tools), 5)

    def test_an_anonymous_assistant_gets_four(self):
        self.assertEqual(len(self._assistant().tools), 4)

    def test_tools_can_still_be_switched_off_entirely(self):
        self.assertEqual(self._assistant(use_tools=False).tools, [])


class SiteSearchTests(TestCase):
    """The assistant's two search tools, on the one corpus.

    They used to query `BlogPost.embedding` and `Project.embedding` directly:
    one vector per row, no record of which model produced it, and a second
    corpus alongside the one `Memory` maintains. Neither was ever fully
    populated and neither knew about the other, so which answer the assistant
    gave depended on which store its tools happened to read.
    """

    def setUp(self):
        from knowledge_base.models import EmbeddingSpace

        EmbeddingSpace.objects.filter(status=EmbeddingSpace.ACTIVE).update(
            status=EmbeddingSpace.RETIRED,
        )
        self.space = EmbeddingSpace.objects.create(
            provider="test", model_id="test-embed", dimensions=8,
            status=EmbeddingSpace.ACTIVE,
        )

        from ai_workflows.harness.memory import Memory

        self.memory = Memory(embedder=_StubEmbedder(), scope="site")

    def _remember(self, title, text, kind, scope="site"):
        from ai_workflows.harness.memory import Memory

        return Memory(embedder=_StubEmbedder(), scope=scope).remember(
            text, title=title, kind=kind,
        )

    def _search(self, tool, query):
        """Run a search tool with the embedder stubbed, as the tools resolve
        it lazily through `llm.get_embedder`."""
        with patch("ai_workflows.harness.llm.get_embedder",
                   return_value=_StubEmbedder()):
            return tool(query)

    def test_projects_are_found_through_semantic_memory(self):
        from ai_workflows.tools import search_projects

        self._remember("A school system", "report cards and fees", "project")
        result = self._search(search_projects.func, "school")

        self.assertIn("A school system", result)

    def test_a_project_search_does_not_return_blog_posts(self):
        """The kinds are separate tools because they are separate questions.
        Folding them together would let a post about a project outrank the
        project."""
        from ai_workflows.tools import search_projects

        self._remember("A blog post", "about school systems", "blog_post")
        result = self._search(search_projects.func, "school")

        self.assertNotIn("A blog post", result)

    def test_the_editorial_corpus_stays_out_of_the_assistant_s_answers(self):
        """`scope` is what keeps the newsroom's working notes out of a
        visitor's chat window. An unscoped recall would return both."""
        from ai_workflows.tools import search_projects

        self._remember("Internal dossier", "school systems", "project",
                       scope="editorial")
        result = self._search(search_projects.func, "school")

        self.assertNotIn("Internal dossier", result)

    def test_an_unsearchable_memory_says_so_rather_than_nothing(self):
        """"Nothing found" and "the search is broken" must not read alike: a
        model told nothing was found will confidently say so."""
        from ai_workflows.harness.errors import MemoryUnavailable
        from ai_workflows.tools import search_projects

        with patch("ai_workflows.harness.memory.Memory.recall",
                   side_effect=MemoryUnavailable("no active space")):
            result = search_projects.func("school")

        self.assertIn("could not be searched", result)
        self.assertNotIn("No relevant", result)


class EmbeddingTextTests(TestCase):
    """What gets embedded for a row."""

    def test_the_model_s_own_builder_wins(self):
        """`get_embedding_text()` folds in the title, category and tags. Using
        a single field would silently embed less than the command it replaced,
        and a project would stop matching on its technologies."""
        from ai_workflows.harness.indexing import text_for
        from brand.models import Project

        project = Project.objects.create(
            title="HoloDesk", short_description="Rust, WebGPU",
            description="a spatial workspace",
        )

        text = text_for(project, "description")
        self.assertIn("HoloDesk", text)
        self.assertIn("Rust, WebGPU", text)
        self.assertIn("a spatial workspace", text)

    def test_a_broken_builder_falls_back_to_the_field(self):
        from ai_workflows.harness.indexing import text_for
        from brand.models import Project

        project = Project.objects.create(title="T", description="the body")
        with patch.object(Project, "get_embedding_text",
                          side_effect=ValueError("boom")):
            self.assertEqual(text_for(project, "description"), "the body")


class _StubEmbedder:
    """Deterministic vectors, so a test asserts on ranking rather than luck."""

    def embed_query(self, text):
        return self._vector(text)

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text):
        lowered = (text or "").lower()
        return [
            1.0 if "school" in lowered else 0.0,
            1.0 if "report" in lowered else 0.0,
            1.0 if "blog" in lowered else 0.0,
            1.0, 0.0, 0.0, 0.0, 0.0,
        ]
