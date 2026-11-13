"""The chat assistant, on the harness.

Step 7. What changed and why:

**One definition of the brand voice.** The assistant carried its own hardcoded
identity in a 45-line system prompt while `EditorialMemory.brand_voice` sat in
the database read only by the writer. The company had one voice and the
codebase had two. The persona below says what is specific to *this* agent; the
voice comes from `AgentProfile`, which every other agent now reads too.

**A static system prompt.** The clock has left the prompt for a tool. Provider
prompt caching matches on an exact prefix and the system message is the front
of it, so a clock there meant the highest-volume path in the system could never
get a cache hit. Rounding it to the hour was the conservative half of that fix
and said so in a comment addressed to this step; this is the rest.

**The metadata block is parsed.** The prompt has asked for one since the
assistant was written and nothing ever read it, so the JSON went out as part of
the visible reply and `suggested_questions` left the API hardcoded empty.

**Failures are recorded.** `send_message` still catches -- the edge is the one
place `errors.py` allows that, because a chat view has to render something --
but an unreachable model is now recorded against the agent's health and
alerted on, instead of becoming an apology nobody hears about.
"""
from typing import Optional, TypedDict, List
from dataclasses import dataclass
import logging
import os
import re

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, trim_messages
from langchain_core.messages.utils import count_tokens_approximately
from pydantic import BaseModel, Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import parse_json, strip_fence
from ai_workflows.harness.errors import AgentError, AgentOutputInvalid, ModelUnavailable
from ai_workflows.harness.llm import ModelRole, iter_models
from ai_workflows.harness.memory import Memory
from ai_workflows.harness.persona import Persona
from ai_workflows.harness.retrying import INTERACTIVE, call_with_retries
from brandtechsolution.config import config

logger = logging.getLogger(__name__)

_SENSITIVE_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def _mask_secret(value: str) -> str:
    """Report configuration presence, never credential prefixes/suffixes."""
    return '<configured>' if value else '<empty>'


def _is_sensitive(key: str) -> bool:
    """Return True if `key` looks like it holds a secret/credential value."""
    return any(marker in key.upper() for marker in _SENSITIVE_MARKERS)


def _set_external_environment():
    """
    Expose select configuration values to libraries that read from os.environ.

    Some libraries (like LangChain/LangSmith) read directly from environment variables,
    so we need to set them even though we use config.py as our central source.
    """
    env_overrides = {
        'GOOGLE_API_KEY': config.google_api_key,
        'LANGSMITH_TRACING': 'true' if config.langsmith_tracing else 'false',
        'LANGSMITH_PROJECT': config.langsmith_project,
    }

    # Only set LANGSMITH_API_KEY if it's provided (it's optional)
    if config.langsmith_api_key:
        env_overrides['LANGSMITH_API_KEY'] = config.langsmith_api_key

    # Set LANGSMITH_ENDPOINT if different from default
    if config.langsmith_endpoint != "https://api.smith.langchain.com":
        env_overrides['LANGSMITH_ENDPOINT'] = config.langsmith_endpoint

    for key, value in env_overrides.items():
        if value is not None:
            os.environ[key] = str(value)
            # Log config for debugging, never even partial credential values.
            if _is_sensitive(key):
                logger.debug('[LangSmith] %s=%s', key, _mask_secret(value))
            else:
                logger.debug(f"[LangSmith] {key}={value}")


_set_external_environment()

# Verify LangSmith configuration after setting environment variables
if config.langsmith_tracing:
    # Verify environment variables were set correctly (for external libraries)
    langsmith_tracing_env = os.environ.get('LANGSMITH_TRACING', '').lower()

    if langsmith_tracing_env == 'true' and config.langsmith_api_key:
        logger.info(f"[LangSmith] Tracing enabled for project: {config.langsmith_project}")
    else:
        logger.warning(
            f"[LangSmith] Tracing configured but may not work: "
            f"LANGSMITH_TRACING={langsmith_tracing_env}, "
            f"LANGSMITH_API_KEY={'set' if config.langsmith_api_key else 'NOT SET'}, "
            f"LANGSMITH_PROJECT={config.langsmith_project}"
        )


# ============================================================
# Who it is, and what shape its answer takes
# ============================================================
#
# Two blocks, because they are two different things. A persona says who the
# agent is and how it behaves; the format block says what shape the answer
# takes. `harness.persona` keeps format out of Persona deliberately -- most of
# what the old prompts did was beg for JSON, and an identity and a format
# fighting inside one call produces neither well.

ASSISTANT_PERSONA = Persona(
    name="assistant",
    role=(
        "the Teklora Solutions assistant: a professional, concise technical "
        "assistant for web development, digital transformation, and the "
        "company's published content"
    ),
    directives=(
        "Answer from Teklora's own blog posts and projects, using the search "
        "tools for anything that depends on current site content.",
        "Draw on the conversation history where it is relevant, and not otherwise.",
        "Ask one concise clarifying question when a request is ambiguous or "
        "missing something critical, rather than guessing.",
        "Give actionable recommendations with their tradeoffs when asked for "
        "an opinion.",
        "Keep replies short: one to five paragraphs, bullets for steps or options.",
        "Call `current_time` when the answer depends on today's date or the time.",
    ),
    constraints=(
        "Do not invent search results. If you call a tool, use what it returned.",
        "Do not claim the site covers something you did not find -- say you "
        "could not find it.",
        "Do not return raw JSON as the whole reply.",
        "Refuse anything illegal or unsafe, briefly, and offer a safe alternative.",
    ),
)

RESPONSE_FORMAT = """Reply with a natural, human-readable message. WhatsApp-style
formatting is fine where it helps.

When you used a tool, or when there are useful follow-ups, end the reply with a
metadata block: the literal word METADATA on its own line, then a fenced JSON
object.

METADATA
```json
{"sources": [{"type": "blog", "id": 12, "title": "A post", "excerpt": "Up to 250 characters."}],
 "follow_up_questions": ["A question the user might ask next"]}
```

`type` is "blog" or "project"; `id` is the numeric id or null. The block is
stripped before the reply reaches the user, so never mention it in your prose.
If you found nothing relevant, say so in the reply and send an empty `sources`."""


class Source(BaseModel):
    """One thing the assistant says it drew on."""

    type: str = ""
    id: int | None = None
    title: str = ""
    excerpt: str = ""


class ReplyMetadata(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)


# The literal marker, then a fenced object or a bare one, at the very end.
# Anchoring on the marker rather than on "a trailing JSON-looking thing" is what
# makes stripping safe: ordinary prose does not contain a lone METADATA line.
_METADATA_BLOCK = re.compile(
    r"\n\s*METADATA\s*\n+(```(?:json)?\s*.*?\s*```|\{.*\})\s*$",
    re.DOTALL | re.IGNORECASE,
)


def split_metadata(text):
    """Separate the user-visible reply from its metadata block.

    The prompt has asked for this block since the assistant was written, the
    model has been producing it, and nothing ever parsed it -- so the JSON was
    shown to the user as part of the answer, and `suggested_questions` left the
    API hardcoded empty. This is the missing half.

    A block that matches the marker but does not parse is still removed, and the
    failure logged. The marker is unambiguous, so the alternative is showing
    somebody a broken JSON blob, which is not an improvement on a valid one.
    """
    text = text or ""
    match = _METADATA_BLOCK.search(text)
    if not match:
        return text.strip(), ReplyMetadata()

    reply = text[: match.start()].strip()
    try:
        metadata = parse_json(strip_fence(match.group(1)), ReplyMetadata)
    except AgentOutputInvalid as exc:
        logger.warning("[assistant] could not parse the metadata block: %s", exc)
        metadata = ReplyMetadata()

    return reply, metadata


def system_prompt(persona=None):
    """The assistant's system message: persona and voice, then output contract.

    Static, and that is the point. It used to carry a clock -- at second
    granularity first, then rounded to the hour -- and provider prompt caching
    matches on an exact prefix, so every request produced a prefix that could
    never hit. Rounding was the conservative half of that fix, with a comment
    saying the rest belonged with the harness work. This is the rest: the
    assistant has not stopped knowing the time, it looks it up with
    `current_time` when the answer actually depends on it.
    """
    persona = persona or ASSISTANT_PERSONA
    return f"{persona.render()}\n\n{RESPONSE_FORMAT}"


class AssistantResponse(TypedDict):
    """Response structure from the assistant."""
    response: str
    suggested_questions: List[str]
    sources: List[dict]


@dataclass
class ChatContext:
    """Runtime context for the chat assistant."""
    user_id: Optional[int] = None
    is_authenticated: bool = False


class ChatAssistant(Agent):
    """The conversational agent.

    Usage:
        assistant = ChatAssistant(thread_id="unique_thread_id")
        response = assistant.send_message("Hello!")
        print(response["response"])
    """

    name = "assistant"
    persona = ASSISTANT_PERSONA
    model_role = ModelRole.CONVERSATIONAL
    tool_suite = "assistant"
    memory_scope = "site"

    MAX_TOKENS_FOR_TRIMMING = 2000

    def __init__(
        self,
        thread_id: str,
        user_id: Optional[int] = None,
        use_tools: bool = True,
    ):
        """
        Args:
            thread_id: Required unique identifier for this conversation
            user_id: Optional user ID if authenticated
            use_tools: Whether to enable RAG tools (default True)
        """
        self.thread_id = thread_id
        self.user_id = user_id

        logger.info(f"[ChatAssistant] Initializing with thread_id={thread_id}, user_id={user_id}, use_tools={use_tools}")

        self.config = {
            "configurable": {"thread_id": thread_id},
            "workflow_type": "chatbot",
        }
        if user_id:
            self.config["user_id"] = user_id

        # Episodic memory through the one facade rather than a direct
        # DjangoCheckpointer import. Same checkpointer, reached the same way
        # every other agent reaches its stores.
        self.memory = Memory(scope=self.memory_scope)
        self.checkpointer = self.memory.thread(thread_id)

        # Resolved on first use, not here. `get_history` only needs the
        # checkpointer, and making the constructor resolve a model meant that
        # during a provider outage a user could not even read what they had
        # already said -- the history endpoint returned 500. Deferring it also
        # keeps the tool wiring below testable without a credential.
        self._model = None
        self._app = None
        # The preference order, walked one provider at a time. Held on the
        # instance rather than rebuilt per call so that a provider which has
        # already failed this conversation is not offered again.
        self._candidates = None
        self._provider = None
        self._outages = []
        # How far into this thread's message list usage has already been
        # recorded. None until the thread's existing length is known: a
        # conversation resumed from the checkpointer arrives with its whole
        # history, and starting at zero would bill every earlier turn again on
        # every turn.
        self._accounted_messages = None

        # Tools come from the harness registry. "Which agent can reach what"
        # lives in one table (harness/tools.py SUITES) rather than in each
        # agent's constructor. The user info tool is still bound per call, and
        # is still omitted entirely for an anonymous caller.
        self.tools = []
        if use_tools:
            from ai_workflows.harness.tools import (
                ToolContext, register_builtin_tools, suite_for,
            )

            register_builtin_tools()
            self.tools = suite_for(
                self.tool_suite,
                ToolContext(user_id=self.user_id, thread_id=self.thread_id),
            )

        logger.info(f"[ChatAssistant] Tools configured: {len(self.tools)} tools")

        self._system_prompt = system_prompt(self.voiced_persona())

    @property
    def model(self):
        """The chat model, resolved on first use.

        Raises `ModelUnavailable` rather than returning None -- that is the
        whole point of resolution existing. `allow_fallback` is honoured, so
        the assistant survives one provider going down.
        """
        if self._model is None:
            self._next_provider()
        return self._model

    def _next_provider(self):
        """Move to the next provider the catalogue offers.

        Resolution that only picks a provider covers one that is misconfigured,
        not one that is *exhausted*: a rate limit arrives at invoke time, when
        the client has long since been built. The assistant holds its client
        for a whole conversation, so the provider chosen at the first message
        is the one still in use when a quota runs out twenty messages later,
        and re-resolving from the top would hand back that same provider --
        it builds perfectly well.
        """
        if self._candidates is None:
            self._candidates = iter_models(
                self.model_role, agent=self.name,
                allow_fallback=self.allow_fallback,
            )

        try:
            self._provider, self._model = next(self._candidates)
        except StopIteration:
            raise ModelUnavailable(
                "every provider has been tried for this conversation: "
                + ("; ".join(self._outages) or "none is usable"),
                agent=self.name,
            ) from None

        # A different client means the compiled graph is stale.
        self._app = None

    @property
    def app(self):
        if self._app is None:
            self._app = self._create_agent()
        return self._app

    def _create_agent(self):
        """Create the LangChain agent with middleware."""

        def _modifier(state):
            messages = state["messages"] if isinstance(state, dict) else state

            if not messages:
                trimmed = messages
            else:
                trimmed = trim_messages(
                    messages=messages,
                    max_tokens=self.MAX_TOKENS_FOR_TRIMMING,
                    token_counter=count_tokens_approximately,
                    strategy="last",
                    allow_partial=True,
                    include_system=True,
                    start_on="human",
                    end_on=["human", "tool", "ai"],
                )
                if len(trimmed) != len(messages):
                    logger.info(f"[ChatAssistant] Trimmed messages from {len(messages)} to {len(trimmed)}")

            # Rendered once in __init__, not per call. It has no per-request
            # content any more, so re-rendering it would only risk
            # reintroducing some.
            return [SystemMessage(content=self._system_prompt)] + trimmed

        app = create_react_agent(
            model=self.model,
            tools=self.tools,
            prompt=_modifier,
            checkpointer=self.checkpointer,
        )
        logger.info("[ChatAssistant] Agent created successfully with checkpointer")
        return app

    # ------------------------------------------------------------------
    # harness entry point
    # ------------------------------------------------------------------

    def run(self, request: AgentRequest) -> AgentResult:
        """Answer one message. Raises; `send_message` is the edge that catches."""
        message = request.payload["message"]

        output = self._invoke({"messages": [HumanMessage(content=message)]})

        reply, metadata = split_metadata(_content_of(output.get("messages", [])))

        return AgentResult(
            agent=self.name,
            output=reply,
            metadata={
                "sources": [s.model_dump() for s in metadata.sources],
                "follow_up_questions": metadata.follow_up_questions,
                "thread_id": self.thread_id,
            },
        )

    def _mark_history(self):
        """Note how many messages the thread already had, once per instance.

        Read from the checkpointer rather than counted as we go, because this
        instance may be the first to touch a conversation that is already
        twenty turns old -- `_account` cannot tell those apart from the ones
        this turn produced.
        """
        if self._accounted_messages is not None:
            return
        try:
            snapshot = self.app.get_state(self.config)
            existing = (getattr(snapshot, "values", None) or {}).get("messages") or []
            self._accounted_messages = len(existing)
        except Exception as exc:  # noqa: BLE001 - bookkeeping never blocks a reply
            logger.warning(
                "[ChatAssistant] could not read the thread length for "
                "accounting: %s", exc,
            )

    def _account(self, state):
        """Record what the graph's model calls consumed.

        The graph returns conversation state rather than a response, so the
        usage has to be read off the messages it produced. Only the ones this
        turn added: the thread carries the whole history, and re-reading it
        each turn would bill the first message once per turn for the life of
        the conversation, which is a spend report that grows quadratically
        while the spend does not.

        Wrapped whole, because this runs inside `_invoke`'s try block on the
        *success* path. An exception escaping here would be caught as a
        provider failure and send a perfectly good reply off to failover --
        bookkeeping turning a working conversation into an outage.
        """
        try:
            self._account_messages(state)
        except Exception as exc:  # noqa: BLE001 - see the docstring
            logger.warning("[ChatAssistant] could not account for usage: %s", exc)

    def _account_messages(self, state):
        from ai_workflows.harness import usage

        if self._accounted_messages is None:
            # The baseline was not established, so there is no way to tell this
            # turn's messages from the history. Skip rather than guess: a
            # missing line in a spend report is recoverable, and a report that
            # re-bills the whole conversation on every turn is not.
            logger.warning(
                "[ChatAssistant] usage not accounted for this turn: the "
                "thread's prior length was unknown"
            )
            return

        messages = (state or {}).get("messages") or []
        for message in messages[self._accounted_messages:]:
            # Only a model response can carry token counts. The human turn and
            # every tool result are new messages too, and recording them meant
            # `usage.record` logged "reported no token counts" for each one --
            # so a perfectly healthy turn wrote a line that reads exactly like
            # an accounting gap. A tool-calling turn produced two of them, and
            # the first thing that log did in production was send someone
            # hunting a bug that was not there.
            if not isinstance(message, AIMessage):
                continue
            usage.record(
                message,
                provider=self._provider.value if self._provider else "",
                model=getattr(self._model, "model", ""),
                agent=self.name,
                role=str(getattr(self.model_role, "value", self.model_role)),
            )
        self._accounted_messages = len(messages)

    def _invoke(self, payload):
        """Run the graph, moving to the next provider if one cannot answer.

        The retry resumes rather than repeats. LangGraph checkpoints the input
        before the model node runs, so a second `invoke` carrying the same
        payload would write the user's message into the thread twice and they
        would see themselves saying it twice -- an outage turned into a visible
        mess in the transcript. Passing `None` resumes the thread from the
        message that is already there.
        """
        first = True
        self._mark_history()

        while True:
            try:
                # A short wait covers a momentary spike. Short, because
                # somebody is watching a chat box: a minute of silence reads
                # as a broken site, so anything longer belongs to the
                # failover below rather than to patience.
                state = call_with_retries(
                    lambda: self.app.invoke(payload if first else None, self.config),
                    policy=INTERACTIVE,
                    label=self._provider.value if self._provider else "",
                    agent=self.name,
                )
                self._account(state)
                return state
            except AgentError:
                raise
            except Exception as exc:  # noqa: BLE001 - re-raised as our own type
                label = self._provider.value if self._provider else "the model"

                if not self.allow_fallback:
                    raise ModelUnavailable(
                        f"the conversation graph failed: {exc}", agent=self.name,
                        provider=label,
                    ) from exc

                self._outages.append(f"{label}: {exc}")
                logger.warning(
                    "[ChatAssistant] %s could not answer, trying the next "
                    "provider: %s", label, exc,
                )

                # The input is checkpointed, so from here the thread resumes.
                first = False
                self._model = None
                try:
                    self._next_provider()
                except ModelUnavailable as spent:
                    raise spent from exc

    # ------------------------------------------------------------------
    # the edge
    # ------------------------------------------------------------------

    def send_message(self, message: str) -> AssistantResponse:
        """Send a message and get a response.

        This is the edge, and the edge is the one place `errors.py` allows an
        agent error to be caught and turned into content -- a chat view has to
        render something. What is new is that the failure is also *recorded*:
        `execute` marks the agent unhealthy and step 5's alerting pages
        whoever holds `receive_alerts`, so an apology to one user is no longer
        the only trace of a dead provider.
        """
        logger.info(f"[ChatAssistant] Sending message to thread_id={self.thread_id}, user_id={self.user_id}")

        try:
            result = self.execute(AgentRequest(
                payload={"message": message},
                thread_id=self.thread_id,
                user_id=self.user_id,
            ))
        except AgentError as exc:
            logger.error("[ChatAssistant] %s", exc)
            return {
                "response": (
                    "I can't reach my tools right now, so I'd rather not guess. "
                    "Please try again shortly."
                ),
                "suggested_questions": [],
                "sources": [],
            }
        except Exception:  # noqa: BLE001
            logger.exception("[ChatAssistant] unexpected failure in send_message")
            return {
                "response": (
                    "I hit an unexpected problem handling that message. "
                    "Please try again."
                ),
                "suggested_questions": [],
                "sources": [],
            }

        logger.info(f"[ChatAssistant] Generated response (length: {len(result.output)})")
        return {
            "response": result.output,
            "suggested_questions": result.metadata.get("follow_up_questions", []),
            "sources": result.metadata.get("sources", []),
        }

    def _extract_content_from_stringified(self, msg_str: str) -> Optional[str]:
        """
        Extract content from a stringified LangChain message object.

        Handles formats like:
        - content='Hello' additional_kwargs={} ...
        - content=[{'type': 'text', 'text': 'Hello...'}] ...

        Returns:
            Extracted content string, or None if parsing fails
        """
        match = re.search(r"content='([^']*)'", msg_str)
        if match:
            return match.group(1)

        match = re.search(r"'text':\s*'([^']*)'", msg_str)
        if match:
            return match.group(1)

        if "content=''" in msg_str or 'content=""' in msg_str:
            return ""

        return None

    def _get_role_from_stringified(self, msg_str: str) -> str:
        """
        Determine role from a stringified message.

        Returns:
            'user' or 'assistant'
        """
        if msg_str.startswith("HumanMessage") or "HumanMessage(" in msg_str:
            return "user"
        if msg_str.startswith("AIMessage") or "AIMessage(" in msg_str:
            return "assistant"
        if "function_call" in msg_str or "tool_calls" in msg_str:
            return "assistant"
        return "user"

    def get_history(self) -> List[dict]:
        """
        Get conversation history for this thread.

        Returns:
            List of message dicts with role and content
        """
        try:
            checkpoint = self.checkpointer.get_tuple(self.config)
            if not checkpoint:
                logger.info(f"[ChatAssistant] No checkpoint found for thread_id={self.thread_id}")
                return []

            messages = checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
            logger.info(f"[ChatAssistant] Found {len(messages)} messages in checkpoint")
            history = []

            for msg in messages:
                content = None
                role = "user"

                if hasattr(msg, "content"):
                    role = "assistant" if isinstance(msg, AIMessage) else "user"
                    content = msg.content

                elif isinstance(msg, dict):
                    msg_type = msg.get("type", msg.get("role", "unknown"))
                    if msg_type in ("human", "user"):
                        role = "user"
                    elif msg_type in ("ai", "assistant"):
                        role = "assistant"
                    else:
                        role = "user"
                    content = msg.get("content", "")

                elif isinstance(msg, str):
                    role = self._get_role_from_stringified(msg)
                    content = self._extract_content_from_stringified(msg)
                    if content is None:
                        continue

                if content is None or content == "":
                    continue

                if isinstance(content, list):
                    content = _flatten_parts(content)
                    if content is None:
                        continue

                # Tool errors that got stored as if they were replies.
                content_str = str(content).lower()
                if any(indicator in content_str for indicator in [
                    "error searching",
                    "error embedding",
                    "resource_exhausted",
                    "429 resource_exhausted",
                    "quota exceeded",
                    "error:",
                ]):
                    continue

                # The metadata block is not part of the conversation either.
                # Without this, replies saved before step 7 read back with
                # their JSON attached.
                visible, _ = split_metadata(str(content))
                if not visible:
                    continue

                history.append({"role": role, "content": visible})

            logger.info(f"[ChatAssistant] Returning {len(history)} messages from history")
            return history

        except Exception as e:
            logger.error(f"[ChatAssistant] Error getting history: {e}", exc_info=True)
            return []


def _flatten_parts(content):
    """Gemini returns content as a list of parts; join the text ones."""
    text_parts = [
        part["text"] if isinstance(part, dict) and "text" in part else part
        for part in content
        if isinstance(part, str) or (isinstance(part, dict) and "text" in part)
    ]
    return "\n".join(text_parts) if text_parts else None


def _content_of(messages):
    """The text of the last message in a graph output."""
    if not messages:
        return ""

    last = messages[-1]
    if hasattr(last, "content"):
        content = last.content
    elif isinstance(last, dict):
        content = last.get("content", str(last))
    else:
        content = str(last)

    if isinstance(content, list):
        return _flatten_parts(content) or str(content)
    return str(content)


# Convenience function for simple usage (backwards compatibility)
def get_chatbot_response(
    message: str,
    thread_id: str,
    user_id: Optional[int] = None,
) -> dict:
    """
    Get chatbot response for a message.

    Args:
        message: User message
        thread_id: Thread ID for conversation
        user_id: Optional user ID

    Returns:
        Dict with response and metadata
    """
    logger.info(f"[get_chatbot_response] Called with thread_id={thread_id}, user_id={user_id}")

    try:
        assistant = ChatAssistant(thread_id=thread_id, user_id=user_id)
    except AgentError as exc:
        # Construction no longer resolves a model, so this is rarer than it
        # was -- but a bad thread_id or a missing checkpointer table still
        # lands here, and there is no agent instance to record it against.
        from ai_workflows.harness.alerts import record_failure

        logger.error("[get_chatbot_response] %s", exc)
        record_failure("assistant", exc, provider=exc.provider or "")
        return {
            "response": (
                "I can't reach my tools right now, so I'd rather not guess. "
                "Please try again shortly."
            ),
            "thread_id": thread_id,
            "metadata": {"suggested_questions": [], "sources": []},
        }

    result = assistant.send_message(message)

    return {
        "response": result["response"],
        "thread_id": thread_id,
        "metadata": {
            "suggested_questions": result.get("suggested_questions", []),
            "sources": result.get("sources", []),
        },
    }
