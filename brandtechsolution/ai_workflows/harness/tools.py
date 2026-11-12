"""One tool registry, and the suite each agent is issued.

Tools were chat-only. `search_blog_posts`, `search_projects` and a per-user
info tool were bound to the assistant and nothing else -- so the research agent
could not search the knowledge base its own pipeline populates, and the fact
verifier checked claims against the model's own weights with no tools at all.

Two kinds of tool, because the existing three are already both kinds:

- **static** -- the same object for every caller (`search_blog_posts`).
- **bound** -- built per request from runtime context, because the tool closes
  over something only the caller knows. `get_user_info` has to be bound to a
  user id; a shared instance would answer for whoever called it last, which is
  a data leak rather than a design preference.

Suites are declared here rather than on each agent so that "who can reach
what" is answerable by reading one table.
"""
import logging
from dataclasses import dataclass

from ai_workflows.harness.errors import ToolFailed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolContext:
    """What a bound tool needs to know about this call."""

    user_id: int | None = None
    thread_id: str = ""
    run_id: int | None = None


class ToolRegistry:
    """name -> tool, for both kinds."""

    def __init__(self):
        self._static = {}
        self._factories = {}

    def register(self, name, tool):
        self._guard(name)
        self._static[name] = tool
        return tool

    def register_factory(self, name, factory):
        """Register a tool that must be built per call.

        `factory` takes a ToolContext and returns a tool, or None when the
        context cannot support it -- an unauthenticated caller has no user for
        `get_user_info` to describe, and omitting the tool is better than
        offering one that will fail.
        """
        self._guard(name)
        self._factories[name] = factory
        return factory

    def _guard(self, name):
        if name in self._static or name in self._factories:
            raise ValueError(f"a tool named {name!r} is already registered")

    def names(self):
        return sorted({*self._static, *self._factories})

    def __contains__(self, name):
        return name in self._static or name in self._factories

    def resolve(self, names, context=None):
        """Build the tool objects for `names`.

        An unknown name raises rather than being skipped: a suite naming a tool
        that does not exist is a typo, and silently handing the agent a shorter
        list would show up much later as the model mysteriously declining to
        look something up.
        """
        context = context or ToolContext()
        tools = []

        for name in names:
            if name in self._static:
                tools.append(self._static[name])
                continue

            factory = self._factories.get(name)
            if factory is None:
                raise ToolFailed(
                    f"no tool named {name!r} (registered: {', '.join(self.names())})",
                    tool=name,
                )

            built = factory(context)
            if built is not None:
                tools.append(built)

        return tools


registry = ToolRegistry()


# ============================================================
# Suites
# ============================================================
# Which tools each agent is issued.
#
# Step 4 left the newsroom suites empty on purpose, with a note saying that
# giving them `search_knowledge` and `fetch_url` changes what they can *do* --
# the fact verifier would start checking claims against real sources rather
# than against the model's own weights -- and that belonged behind its own
# review rather than smuggled in with a refactor. Step 9 is that review.
#
# Who gets what, and why not everyone:
#
#   fact_verifier  both. It is the agent whose entire job is checking claims
#                  against something outside itself, and until now the
#                  something was the model's own weights.
#   research       both. It cites sources; it should be able to read them.
#   writer         search_knowledge only. It writes from the verified report
#                  and must not acquire new material at the drafting stage --
#                  that is how an unsupported claim gets back in after the
#                  verifier removed it. Reading past coverage for continuity
#                  is different, and useful.
#   social         nothing. It adapts an article that is already written and
#                  verified. A tool here could only add something the article
#                  does not say.
#   trend_*        nothing yet. Scoring and forecasting from live sources is a
#                  real idea and a different conversation.

SUITES = {
    # The assistant's three, plus the clock. `current_time` is not a new
    # capability so much as a relocated one: the date and time used to be
    # interpolated into the system prompt on every request, which is the front
    # of the cached prefix, so the highest-volume path in the system could
    # never get a prompt-cache hit. As a tool the assistant looks the time up
    # when the answer depends on it, and the prompt is static. The public
    # library tool adds only administrator-approved references, never private uploads.
    "assistant": ["search_blog_posts", "search_projects", "user_info", "current_time", "search_public_library"],

    # Listed explicitly even when empty, so a gap is visible rather than
    # looking like an oversight.
    "trend_intelligence": [],
    "trend_prediction": [],
    "research": ["search_knowledge", "fetch_url", "search_public_library"],
    "fact_verifier": ["search_knowledge", "fetch_url", "search_public_library"],
    "writer": ["search_knowledge", "search_public_library"],
    "social": [],

    # Not an agent that dispatches: the newsroom runs its subagents, each of
    # which is issued its own suite above.
    "newsroom": [],
}


def suite_for(agent_name, context=None, *, registry=registry):
    """The tool objects `agent_name` is issued.

    An agent with no suite gets no tools rather than every tool. Defaulting to
    everything would mean a new tool silently became available to agents nobody
    considered when adding it.
    """
    names = SUITES.get(agent_name)
    if names is None:
        logger.info("[tools] %s has no declared suite; issuing no tools", agent_name)
        return []
    return registry.resolve(names, context)


def register_builtin_tools(target=registry):
    """Move the three existing tools into the registry.

    Imported lazily: ai_workflows.tools pulls in the embedding client and the
    retrievers, and importing the registry should not drag those in.
    """
    from ai_workflows.tools import (
        create_user_info_tool,
        current_time,
        fetch_url,
        search_blog_posts,
        search_knowledge,
        search_projects,
    )

    if 'search_public_library' not in target:
        from knowledge_base.library.tools import search_public_library
        target.register('search_public_library', search_public_library)

    if "search_blog_posts" not in target:
        target.register("search_blog_posts", search_blog_posts)
    if "search_projects" not in target:
        target.register("search_projects", search_projects)
    if "current_time" not in target:
        target.register("current_time", current_time)
    if "search_knowledge" not in target:
        target.register("search_knowledge", search_knowledge)
    if "fetch_url" not in target:
        target.register("fetch_url", fetch_url)

    if "user_info" not in target:
        target.register_factory(
            "user_info",
            # None for an anonymous caller: there is no user to describe, and
            # a tool that always fails is worse than an absent one.
            lambda ctx: create_user_info_tool(ctx.user_id) if ctx.user_id else None,
        )

    return target
