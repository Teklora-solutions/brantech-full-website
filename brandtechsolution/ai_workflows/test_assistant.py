"""Step 7: the assistant on the harness.

Three things changed that a user or an operator would notice, and each has its
own class below: the metadata block stops leaking into replies, an unreachable
model stops being a private apology, and the brand voice stops being defined
twice.
"""
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.test import TestCase
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


from ai_workflows.harness.alerts import ALERT_CAPABILITY
from ai_workflows.harness.errors import ModelUnavailable
from ai_workflows.models import AgentHealth, AgentProfile
from ai_workflows.service import (
    ChatAssistant,
    ReplyMetadata,
    get_chatbot_response,
    split_metadata,
    system_prompt,
)


class FakeGraph:
    """Stands in for the compiled react agent."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def invoke(self, state, config=None, **kwargs):
        self.calls.append(state)
        return {"messages": [type("M", (), {"content": self.reply})()]}


def _assistant(reply="Hello.", **kwargs):
    """An assistant with its graph injected.

    Injected rather than patched at construction: since the model is resolved
    lazily -- so that reading history does not require a working provider --
    the graph is not built until first use, by which point a patch applied
    around the constructor has long since exited.
    """
    assistant = ChatAssistant(thread_id="t-1", **kwargs)
    assistant._app = FakeGraph(reply)
    # One provider and no more. Without this, a test that makes the graph fail
    # would send the assistant looking for a second provider, resolve one for
    # real off the environment's key, and make a live billed call in the middle
    # of the suite. Failover has its own tests, which supply their own
    # providers; these ones are about what happens when there is nowhere to go.
    assistant._candidates = iter(())
    return assistant


REPLY_WITH_METADATA = """Teklora builds responsive sites with Django and React.

METADATA
```json
{"sources": [{"type": "project", "id": 1, "title": "Test Project", "excerpt": "A React app."}],
 "follow_up_questions": ["Want links to the project?"]}
```"""


class MetadataTests(TestCase):
    """The block the prompt has always asked for and nothing ever read."""

    def test_the_block_is_stripped_from_what_the_user_sees(self):
        reply, _ = split_metadata(REPLY_WITH_METADATA)
        self.assertNotIn("METADATA", reply)
        self.assertNotIn("sources", reply)
        self.assertTrue(reply.endswith("Django and React."))

    def test_the_block_is_parsed_rather_than_discarded(self):
        _, metadata = split_metadata(REPLY_WITH_METADATA)
        self.assertEqual(len(metadata.sources), 1)
        self.assertEqual(metadata.sources[0].title, "Test Project")
        self.assertEqual(metadata.follow_up_questions, ["Want links to the project?"])

    def test_a_reply_without_a_block_is_untouched(self):
        reply, metadata = split_metadata("Just an answer.")
        self.assertEqual(reply, "Just an answer.")
        self.assertEqual(metadata, ReplyMetadata())

    def test_prose_mentioning_metadata_is_not_mistaken_for_a_block(self):
        """Anchored on a lone marker line, so ordinary prose is safe."""
        text = "The METADATA field in that schema is optional."
        reply, _ = split_metadata(text)
        self.assertEqual(reply, text)

    def test_an_unfenced_block_is_still_understood(self):
        reply, metadata = split_metadata(
            'An answer.\n\nMETADATA\n{"follow_up_questions": ["And then?"]}'
        )
        self.assertEqual(reply, "An answer.")
        self.assertEqual(metadata.follow_up_questions, ["And then?"])

    def test_a_malformed_block_is_removed_and_logged(self):
        """Showing somebody broken JSON is not better than showing valid JSON."""
        with self.assertLogs("ai_workflows.service", level="WARNING"):
            reply, metadata = split_metadata("An answer.\n\nMETADATA\n```json\n{oops\n```")

        self.assertEqual(reply, "An answer.")
        self.assertEqual(metadata, ReplyMetadata())

    def test_the_reply_reaching_the_caller_carries_both_halves(self):
        result = _assistant(REPLY_WITH_METADATA).send_message("hi")

        self.assertNotIn("METADATA", result["response"])
        self.assertEqual(result["suggested_questions"], ["Want links to the project?"])
        self.assertEqual(result["sources"][0]["title"], "Test Project")

    def test_suggested_questions_are_no_longer_hardcoded_empty(self):
        """They were declared on the TypedDict, asked for in the prompt,
        produced by the model, and returned as [] regardless."""
        plain = _assistant("No metadata here.").send_message("hi")
        self.assertEqual(plain["suggested_questions"], [])

        rich = _assistant(REPLY_WITH_METADATA).send_message("hi")
        self.assertNotEqual(rich["suggested_questions"], [])


class HistoryTests(TestCase):
    def test_history_does_not_replay_metadata_blocks(self):
        """Replies saved before step 7 have their JSON attached."""
        assistant = _assistant()
        checkpoint = type("C", (), {"checkpoint": {
            "channel_values": {"messages": [
                {"type": "ai", "content": REPLY_WITH_METADATA},
            ]}
        }})()

        with patch.object(assistant.checkpointer, "get_tuple", return_value=checkpoint):
            history = assistant.get_history()

        self.assertEqual(len(history), 1)
        self.assertNotIn("METADATA", history[0]["content"])


class FailureTests(TestCase):
    """An outage used to be an apology to one user and nothing else."""

    def setUp(self):
        user = User.objects.create_user("ops", email="ops@example.com", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename=ALERT_CAPABILITY))

    def test_an_unreachable_model_pages_somebody(self):
        with patch("ai_workflows.service.iter_models",
                   side_effect=ModelUnavailable("no key", provider="gemini")):
            result = get_chatbot_response("hi", thread_id="t-1")

        self.assertIn("can't reach my tools", result["response"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("assistant is failing", mail.outbox[0].subject)

    def test_the_user_still_gets_a_usable_reply(self):
        """The edge is the one place errors.py allows a catch: a chat view has
        to render something."""
        with patch("ai_workflows.service.iter_models",
                   side_effect=ModelUnavailable("no key")):
            result = get_chatbot_response("hi", thread_id="t-1")

        self.assertTrue(result["response"])
        self.assertEqual(result["thread_id"], "t-1")
        self.assertEqual(result["metadata"]["suggested_questions"], [])

    def test_a_failure_mid_conversation_is_recorded_too(self):
        assistant = _assistant()
        with patch.object(assistant.app, "invoke", side_effect=RuntimeError("boom")):
            result = assistant.send_message("hi")

        self.assertIn("can't reach my tools", result["response"])
        self.assertTrue(AgentHealth.objects.get(agent="assistant").is_failing)

    def test_recovery_is_announced(self):
        assistant = _assistant()
        with patch.object(assistant.app, "invoke", side_effect=RuntimeError("boom")):
            assistant.send_message("hi")
        mail.outbox.clear()

        assistant.send_message("hi again")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("working again", mail.outbox[0].subject)


class OneBrandVoiceTests(TestCase):
    """The assistant was the codebase's second definition of the brand voice."""

    def test_the_prompt_carries_the_stored_voice(self):
        profile = AgentProfile.load()
        profile.brand_voice = "Terse, sceptical, allergic to adjectives."
        profile.save()

        self.assertIn("allergic to adjectives", _assistant()._system_prompt)

    def test_it_is_the_same_voice_the_newsroom_uses(self):
        from editorial.services.writer import AIWriterAgent

        profile = AgentProfile.load()
        profile.brand_voice = "One voice."
        profile.save()

        self.assertEqual(
            ChatAssistant.persona.with_voice(profile.brand_voice).voice,
            AIWriterAgent().voiced_persona().voice,
        )

    def test_the_declared_personas_are_still_distinct(self):
        """One voice, not one persona."""
        from editorial.services.writer import AIWriterAgent

        self.assertNotEqual(ChatAssistant.persona.role, AIWriterAgent.persona.role)


class HarnessContractTests(TestCase):
    def test_the_assistant_is_dispatchable_like_any_other_agent(self):
        from ai_workflows.harness.base import Agent, AgentRequest

        assistant = _assistant()
        self.assertIsInstance(assistant, Agent)

        result = assistant.run(AgentRequest(payload={"message": "hi"}))
        self.assertEqual(result.agent, "assistant")
        self.assertTrue(result.usable)

    def test_it_declares_its_role_and_suite(self):
        from ai_workflows.harness.llm import ModelRole

        self.assertIs(ChatAssistant.model_role, ModelRole.CONVERSATIONAL)
        self.assertEqual(ChatAssistant.tool_suite, "assistant")

    def test_the_system_prompt_is_built_once_not_per_turn(self):
        """It has no per-request content left, so re-rendering could only
        reintroduce some."""
        assistant = _assistant()
        self.assertEqual(assistant._system_prompt, system_prompt(assistant.voiced_persona()))


class NoProviderTests(TestCase):
    """History has to survive an outage the assistant itself cannot."""

    def test_history_is_readable_with_no_usable_provider(self):
        """The regression that made this lazy.

        Resolving a model in the constructor meant that during a provider
        outage a user could not read what they had already said -- the history
        endpoint returned 500, which is a worse experience than the outage.
        """
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")
            self.assertEqual(assistant.get_history(), [])

    def test_sending_a_message_during_the_outage_still_fails_loudly(self):
        """Lazy is not the same as forgiving."""
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")
            result = assistant.send_message("hi")

        self.assertIn("can't reach my tools", result["response"])

    def test_the_tools_are_still_wired_without_a_provider(self):
        """Tool resolution must not depend on a model being reachable."""
        from ai_workflows.models import Provider as ProviderRow

        ProviderRow.objects.all().delete()
        with patch("ai_workflows.harness.catalogue.can_serve", return_value=False):
            assistant = ChatAssistant(thread_id="t-outage")

        self.assertEqual(len(assistant.tools), 4)


class ChatFailoverTests(TestCase):
    """A rate limit must not take site chat down.

    The same defect a live eval run found in the newsroom's gathering loop,
    in the one place a visitor would see it. Resolution picks a provider that
    *builds*; a 429 arrives later, at invoke time, and the assistant holds its
    client for the length of a conversation.
    """

    def _assistant_over(self, graphs, allow_fallback=True):
        """An assistant whose providers hand back `graphs` in order."""
        from ai_workflows.harness.llm import Provider

        names = [Provider.GEMINI, Provider.OPENROUTER, Provider.ANTHROPIC]
        assistant = ChatAssistant(thread_id="t-failover")
        # A class attribute in production; set here per instance so one test
        # can pin the assistant without pinning the class for the others.
        assistant.allow_fallback = allow_fallback

        assistant._candidates = iter(list(zip(names, range(len(graphs)))))
        remaining = list(graphs)

        def build():
            # Production resolves the model before compiling the graph, which
            # is what names the provider a failure gets blamed on.
            assistant.model
            return remaining.pop(0)

        assistant._create_agent = build
        return assistant

    def _ask(self, assistant):
        from ai_workflows.harness.base import AgentRequest

        return assistant.run(AgentRequest(payload={"message": "hello"}))

    def test_an_exhausted_provider_hands_over_to_the_next(self):
        exhausted = _RaisingGraph(RuntimeError("429 RESOURCE_EXHAUSTED"))
        working = FakeGraph("Hello from the second provider.")

        assistant = self._assistant_over([exhausted, working])
        self.assertIn("second provider", self._ask(assistant).output)

    def test_the_retry_resumes_rather_than_repeats(self):
        """Or the user sees themselves saying the same thing twice.

        LangGraph checkpoints the input before the model node runs, so the
        message is already in the thread when the failure arrives. Passing it
        again would write it a second time.
        """
        exhausted = _RaisingGraph(RuntimeError("429"))
        working = FakeGraph("Answered.")

        self._ask(self._assistant_over([exhausted, working]))

        self.assertEqual(working.calls, [None])

    def test_running_out_of_providers_names_every_one_that_failed(self):
        first = _RaisingGraph(RuntimeError("429 exhausted"))
        second = _RaisingGraph(RuntimeError("401 revoked"))

        with self.assertRaises(ModelUnavailable) as caught:
            self._ask(self._assistant_over([first, second]))

        detail = str(caught.exception)
        self.assertIn("gemini", detail)
        self.assertIn("openrouter", detail)
        self.assertIn("429 exhausted", detail)
        self.assertIn("401 revoked", detail)

    def test_a_pinned_assistant_refuses_to_drift(self):
        exhausted = _RaisingGraph(RuntimeError("429"))
        working = FakeGraph("I could have answered.")

        assistant = self._assistant_over([exhausted, working], allow_fallback=False)
        with self.assertRaises(ModelUnavailable):
            self._ask(assistant)

        self.assertEqual(working.calls, [])


class _RaisingGraph:
    """A compiled graph whose model cannot answer."""

    def __init__(self, error):
        self.error = error
        self.calls = []

    def invoke(self, state, config=None, **kwargs):
        self.calls.append(state)
        raise self.error


class _Snapshot:
    def __init__(self, messages):
        self.values = {"messages": list(messages)}


def _Message(content, usage=None):
    """An AI message carrying token counts, as LangChain normalises them.

    A real `AIMessage` rather than a stand-in with the right attributes. The
    assistant now accounts only for model replies -- a human turn and a tool
    result are new messages too, and recording them logged an accounting gap
    on every healthy turn -- so a double that merely *looked* like a reply
    would be testing a path production no longer takes.
    """
    return AIMessage(
        content=content,
        usage_metadata=usage,
        response_metadata={"model_name": "fake-model"},
    )


class _AccountingGraph:
    """A graph with a history, so the usage watermark can be tested at all."""

    def __init__(self, history=(), produced=()):
        self.history = list(history)
        self.produced = list(produced)

    def get_state(self, config=None):
        return _Snapshot(self.history)

    def invoke(self, state, config=None, **kwargs):
        self.history = self.history + self.produced
        return {"messages": self.history}


USAGE = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


class ChatAccountingTests(TestCase):
    """What a conversation costs.

    The subtle part is the watermark. A thread resumed from the checkpointer
    arrives with its whole history, so accounting everything in the returned
    state would bill every earlier turn again on every turn -- a spend report
    that grows quadratically while the spend does not.
    """

    def _assistant(self, graph):
        assistant = ChatAssistant(thread_id="t-cost")
        assistant._app = graph
        assistant._candidates = iter(())
        return assistant

    def _ask(self, assistant):
        from ai_workflows.harness.base import AgentRequest

        return assistant.run(AgentRequest(payload={"message": "hello"}))

    def test_this_turn_s_reply_is_accounted_for(self):
        from ai_workflows.harness import usage

        graph = _AccountingGraph(produced=[_Message("hi", USAGE)])
        with usage.accounting(label="chat") as ledger:
            self._ask(self._assistant(graph))

        self.assertEqual(ledger.calls, 1)
        self.assertEqual(ledger.prompt_tokens, 10)
        self.assertEqual(ledger.completion_tokens, 20)

    def test_a_resumed_thread_is_not_billed_for_its_history(self):
        from ai_workflows.harness import usage

        history = [_Message(f"turn {i}", USAGE) for i in range(6)]
        graph = _AccountingGraph(history=history,
                                 produced=[_Message("new", USAGE)])

        with usage.accounting() as ledger:
            self._ask(self._assistant(graph))

        # One new message, not seven.
        self.assertEqual(ledger.calls, 1)
        self.assertEqual(ledger.prompt_tokens, 10)

    def test_the_human_turn_and_tool_results_are_not_counted_as_calls(self):
        """A tool-calling turn adds four messages and bills one.

        The other three are the human's question and the tool's answer, which
        carry no token counts because they are not model replies. Recording
        them logged "reported no token counts" once per message, so the
        healthiest possible turn wrote two lines that read exactly like an
        accounting gap -- and the first thing that log did in production was
        send someone hunting a bug that was not there.
        """
        from ai_workflows.harness import usage

        turn = [
            HumanMessage(content="what have you built?"),
            AIMessage(content="", usage_metadata=USAGE,
                      tool_calls=[{"name": "search_projects",
                                   "args": {"query": "projects"},
                                   "id": "call-1"}]),
            ToolMessage(content="a project", tool_call_id="call-1"),
            _Message("here is what we have built", USAGE),
        ]
        graph = _AccountingGraph(produced=turn)

        with usage.accounting() as ledger:
            self._ask(self._assistant(graph))

        # Two model replies, not four messages.
        self.assertEqual(ledger.calls, 2)
        self.assertEqual(ledger.prompt_tokens, 20)
        self.assertEqual(ledger.unmeasured_calls, 0)

    def test_a_second_turn_does_not_re_bill_the_first(self):
        from ai_workflows.harness import usage

        graph = _AccountingGraph(produced=[_Message("reply", USAGE)])
        assistant = self._assistant(graph)

        with usage.accounting() as ledger:
            self._ask(assistant)
            self._ask(assistant)

        self.assertEqual(ledger.calls, 2)

    def test_an_unknown_history_length_skips_rather_than_guesses(self):
        """A missing line in a spend report is recoverable. A report that
        re-bills the whole conversation every turn is not."""
        from ai_workflows.harness import usage

        graph = _AccountingGraph(produced=[_Message("hi", USAGE)])
        graph.get_state = lambda config=None: (_ for _ in ()).throw(
            RuntimeError("checkpointer is unreachable")
        )

        with usage.accounting() as ledger:
            self._ask(self._assistant(graph))

        self.assertEqual(ledger.calls, 0)

    def test_a_reply_that_reports_no_tokens_is_not_recorded_as_free(self):
        from ai_workflows.harness import usage
        from ai_workflows.models import ModelInvocation

        graph = _AccountingGraph(produced=[_Message("hi", None)])
        with usage.accounting() as ledger:
            self._ask(self._assistant(graph))

        self.assertEqual(ledger.unmeasured_calls, 1)
        self.assertEqual(ModelInvocation.objects.count(), 0)

    def test_accounting_never_breaks_the_reply(self):
        """_account runs inside _invoke's try block, on the success path.

        An exception escaping it would be read as a provider failure and send
        a perfectly good reply off to failover -- bookkeeping turning a working
        conversation into an outage.
        """
        from unittest.mock import patch

        graph = _AccountingGraph(produced=[_Message("hi", USAGE)])
        with patch("ai_workflows.harness.usage.record",
                   side_effect=RuntimeError("bookkeeping exploded")):
            result = self._ask(self._assistant(graph))

        self.assertFalse(result.abstained)
        self.assertIn("hi", str(result.output))
