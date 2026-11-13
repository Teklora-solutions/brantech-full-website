"""Chat on more than one provider.

Step 3 built the catalogue -- six adapters, activation states, five hundred
priced models -- and none of it reached `get_model`, which could only ever
construct a Gemini client. So adding an OpenAI key activated a provider that
could not serve a request, and the design doc's claim that "chat is
multi-provider from day one" was not true of the code.

These are about the two rules that keep the wiring honest: a provider must have
a model chosen for it, and failover is opt-out per agent.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from ai_workflows.harness import llm
from ai_workflows.harness.catalogue import (
    can_serve,
    chosen_model,
    model_is_serviceable,
    resolve,
)
from ai_workflows.harness.retrying import NEVER
from ai_workflows.harness.errors import ModelUnavailable
from ai_workflows.harness.llm import (
    OPENAI_COMPATIBLE,
    ModelRole,
    Provider,
    get_embedder,
    get_model,
)
from ai_workflows.models import CatalogueEntry, Provider as ProviderRow


def _provider(name, *, model="a-model", preference=10, status=ProviderRow.ACTIVE,
              enabled=True, catalogued=True):
    row = ProviderRow.objects.create(
        name=name, status=status, enabled=enabled,
        preference=preference, default_model=model,
    )
    if catalogued and model:
        CatalogueEntry.objects.create(
            provider=name, model_id=model, display_name=model, available=True,
        )
    return row


def _with_keys(*names):
    """Pretend these providers have credentials configured."""
    return patch("ai_workflows.harness.catalogue.can_serve",
                 lambda name: name in names)


class BuilderTests(TestCase):
    def test_every_declared_provider_can_be_built(self):
        """A Provider enum member with no builder is a provider that appears in
        the panel and fails on first use."""
        for provider in Provider:
            with self.subTest(provider=provider.value):
                self.assertIn(provider, llm._BUILDERS)

    def test_the_openai_compatible_providers_get_their_own_endpoint(self):
        """DeepSeek, OpenRouter and Codex all document OpenAI-compatible APIs,
        so they share a client class and differ by base_url."""
        with patch("ai_workflows.harness.llm._credential", return_value="sk-test"):
            for provider, expected in OPENAI_COMPATIBLE.items():
                if expected is None:
                    continue
                with self.subTest(provider=provider.value):
                    model = get_model(
                        ModelRole.PRECISE, provider=provider.value, model="m",
                    )
                    self.assertEqual(model.openai_api_base, expected)

    def test_openai_itself_uses_the_default_endpoint(self):
        with patch("ai_workflows.harness.llm._credential", return_value="sk-test"):
            model = get_model(ModelRole.PRECISE, provider="openai", model="m")
        self.assertIsNone(OPENAI_COMPATIBLE[Provider.OPENAI])
        self.assertIsNotNone(model)

    def test_the_role_temperature_reaches_every_provider(self):
        """Roles were tuned against Gemini; they have to survive the move."""
        with patch("ai_workflows.harness.llm._credential", return_value="sk-test"):
            for provider in ("openai", "anthropic", "deepseek"):
                with self.subTest(provider=provider):
                    model = get_model(ModelRole.CREATIVE, provider=provider, model="m")
                    self.assertEqual(model.temperature, llm.ROLE_TEMPERATURE[ModelRole.CREATIVE])

    def test_a_missing_credential_names_the_provider(self):
        with patch("ai_workflows.harness.llm._credential", return_value=""):
            with self.assertRaises(ModelUnavailable) as caught:
                get_model(ModelRole.PRECISE, provider="openai", model="m")
        self.assertIn("openai", str(caught.exception))

    def test_credentials_come_from_the_adapters(self):
        """One definition of where a key lives. The adapters already had to
        know, to verify one; a second copy would drift."""
        with patch("ai_workflows.harness.providers.OpenAIAdapter.credential",
                   return_value="sk-from-the-adapter"):
            self.assertEqual(llm._credential(Provider.OPENAI), "sk-from-the-adapter")


class ResolutionTests(TestCase):
    def test_providers_come_back_in_preference_order(self):
        _provider("gemini", preference=10, model="g")
        _provider("openai", preference=60, model="o")

        with _with_keys("gemini", "openai"):
            self.assertEqual(resolve(), [("gemini", "g"), ("openai", "o")])

    def test_a_provider_with_no_chosen_model_is_skipped(self):
        """Picking one out of five hundred by heuristic is the sort of silent
        guess whose wrong answers look exactly like its right ones."""
        _provider("openai", model="", catalogued=False)

        with _with_keys("openai"):
            self.assertEqual(resolve(), [])

    def test_a_provider_that_cannot_serve_is_skipped(self):
        """OpenRouter is why this exists: its listing is public, so it verifies
        and goes active with no key, and then cannot answer a request."""
        _provider("openrouter", model="m")

        with _with_keys():  # nobody has a key
            self.assertEqual(resolve(), [])

    def test_a_disabled_provider_is_skipped(self):
        _provider("openai", enabled=False)
        with _with_keys("openai"):
            self.assertEqual(resolve(), [])

    def test_an_unverified_provider_is_skipped(self):
        _provider("openai", status=ProviderRow.CANDIDATE)
        with _with_keys("openai"):
            self.assertEqual(resolve(), [])

    def test_a_retired_model_is_skipped(self):
        from django.utils import timezone

        _provider("openai", model="old")
        CatalogueEntry.objects.filter(provider="openai", model_id="old").update(
            deprecated_at=timezone.now() - timezone.timedelta(days=1)
        )
        with _with_keys("openai"):
            self.assertEqual(resolve(), [])

    def test_a_model_missing_from_the_catalogue_is_still_allowed(self):
        """The operator may have chosen it before the first refresh, and
        refusing would make the catalogue a prerequisite for any request."""
        _provider("openai", model="brand-new", catalogued=False)
        with _with_keys("openai"):
            self.assertEqual(resolve(), [("openai", "brand-new")])

    def test_no_fallback_returns_only_the_first(self):
        _provider("gemini", preference=10, model="g")
        _provider("openai", preference=60, model="o")

        with _with_keys("gemini", "openai"):
            self.assertEqual(resolve(allow_fallback=False), [("gemini", "g")])


class ChosenModelTests(TestCase):
    def test_the_stored_choice_wins(self):
        _provider("openai", model="gpt-chosen")
        self.assertEqual(chosen_model("openai"), "gpt-chosen")

    def test_gemini_falls_back_to_its_existing_setting(self):
        """Which is why adding five providers changes nothing for the
        deployment that exists today."""
        from brandtechsolution.config import config

        _provider("gemini", model="", catalogued=False)
        self.assertEqual(chosen_model("gemini"), config.gemini_chat_model)

    def test_every_other_provider_must_be_told(self):
        _provider("openai", model="", catalogued=False)
        self.assertEqual(chosen_model("openai"), "")

    def test_an_unknown_provider_has_no_model(self):
        self.assertEqual(chosen_model("nope"), "")


class ServiceabilityTests(TestCase):
    def test_an_available_model_is_serviceable(self):
        _provider("openai", model="m")
        self.assertTrue(model_is_serviceable("openai", "m"))

    def test_a_withdrawn_model_is_not(self):
        _provider("openai", model="m")
        CatalogueEntry.objects.filter(model_id="m").update(available=False)
        self.assertFalse(model_is_serviceable("openai", "m"))

    def test_a_future_retirement_is_still_serviceable(self):
        """A model retiring next month still answers today."""
        from django.utils import timezone

        _provider("openai", model="m")
        CatalogueEntry.objects.filter(model_id="m").update(
            deprecated_at=timezone.now() + timezone.timedelta(days=30)
        )
        self.assertTrue(model_is_serviceable("openai", "m"))


class FailoverTests(TestCase):
    def setUp(self):
        _provider("gemini", preference=10, model="g")
        _provider("openai", preference=60, model="o")

    def _broken(self, *providers):
        def dead(role, tools, model, **kwargs):
            raise ModelUnavailable("key rejected", model=model)

        return patch.object(llm, "_BUILDERS", {
            **llm._BUILDERS,
            **{Provider(p): dead for p in providers},
        })

    def test_the_first_usable_provider_wins(self):
        with _with_keys("gemini", "openai"), \
                patch("ai_workflows.harness.llm._credential", return_value="k"):
            self.assertEqual(get_model(ModelRole.PRECISE).model, "g")

    def test_a_dead_provider_falls_over_to_the_next(self):
        with _with_keys("gemini", "openai"), \
                patch("ai_workflows.harness.llm._credential", return_value="k"), \
                self._broken("gemini"):
            self.assertEqual(get_model(ModelRole.PRECISE).model_name, "o")

    def test_an_agent_that_must_not_drift_does_not(self):
        """The verifier's output is compared across eval runs. A silent model
        swap mid-comparison makes a change in score unattributable."""
        with _with_keys("gemini", "openai"), \
                patch("ai_workflows.harness.llm._credential", return_value="k"), \
                self._broken("gemini"):
            with self.assertRaises(ModelUnavailable):
                get_model(ModelRole.PRECISE, allow_fallback=False, agent="fact_verifier")

    def test_every_provider_failing_reports_all_of_them(self):
        """One error naming only the last would send you debugging the wrong
        provider."""
        with _with_keys("gemini", "openai"), \
                patch("ai_workflows.harness.llm._credential", return_value="k"), \
                self._broken("gemini", "openai"):
            with self.assertRaises(ModelUnavailable) as caught:
                get_model(ModelRole.PRECISE)

        message = str(caught.exception)
        self.assertIn("gemini", message)
        self.assertIn("openai", message)

    def test_nothing_configured_says_what_to_do_about_it(self):
        ProviderRow.objects.all().delete()
        # No rows *and* no Gemini key, so the fresh-install path below does not
        # apply either.
        with _with_keys(), self.assertRaises(ModelUnavailable) as caught:
            get_model(ModelRole.PRECISE)
        self.assertIn("manage.py providers", str(caught.exception))


class FreshInstallTests(TestCase):
    """A new deployment must work before anyone runs a management command."""

    def test_gemini_serves_with_no_catalogue_at_all(self):
        """Making the catalogue a prerequisite for sending any request would
        turn a new deployment into a puzzle: valid key, nothing works."""
        from brandtechsolution.config import config

        ProviderRow.objects.all().delete()
        with _with_keys("gemini"):
            self.assertEqual(resolve(), [("gemini", config.gemini_chat_model)])

    def test_it_does_not_apply_once_a_refresh_has_run(self):
        """An operator who disabled every provider meant it, and quietly
        re-enabling Gemini behind their back would be worse than failing."""
        _provider("gemini", enabled=False)

        with _with_keys("gemini"):
            self.assertEqual(resolve(), [])

    def test_without_a_gemini_key_there_is_nothing_to_fall_back_to(self):
        ProviderRow.objects.all().delete()
        with _with_keys():
            self.assertEqual(resolve(), [])


class EmbeddingTests(TestCase):
    def test_embeddings_never_fail_over(self):
        """A vector from another model is not differently sized, it is
        meaningless in the same space as the stored ones."""
        with self.assertRaises(ModelUnavailable):
            get_embedder(provider="openai")

    def test_the_chat_providers_do_not_drag_embeddings_with_them(self):
        _provider("openai", preference=1, model="o")
        with _with_keys("openai"), \
                patch("ai_workflows.harness.llm.config") as cfg:
            cfg.google_api_key = "k"
            cfg.gemini_embedding_model = "models/gemini-embedding-001"
            cfg.embedding_backend = 'developer_api'
            embedder = get_embedder()

        # The class is GoogleGenerativeAIEmbeddings; "google" is the marker.
        self.assertIn("google", type(embedder).__name__.lower())


class AgentThreadingTests(TestCase):
    """`allow_fallback` spent four steps as a field nobody read."""

    def test_an_agents_flag_reaches_the_resolver(self):
        from editorial.services.research.fact_verifier import FactVerificationAgent

        with _candidates('{"confidence_level": 0.9, "sanitized_text": "x"}') as get:
            FactVerificationAgent().ask("check this", _FakeSchema)

        self.assertIs(get.call_args.kwargs["allow_fallback"], False)

    def test_an_ordinary_agent_may_fall_over(self):
        from editorial.services.writer import AIWriterAgent

        with _candidates("{}") as get:
            AIWriterAgent().ask("write this", _FakeSchema)

        self.assertIs(get.call_args.kwargs["allow_fallback"], True)

    def test_the_agents_persona_and_role_come_along_too(self):
        from editorial.services.social import MultiPlatformContentAgent

        agent = MultiPlatformContentAgent()
        with _candidates("{}") as get:
            agent.ask("adapt this", _FakeSchema)

        self.assertEqual(get.call_args.kwargs["agent"], "social")
        self.assertEqual(get.call_args[0][0], agent.model_role)


from contextlib import contextmanager  # noqa: E402

from ai_workflows.harness.contract import AgentOutput  # noqa: E402


@contextmanager
def _candidates(content):
    """Stand in for the candidate iterator with one model returning `content`."""
    client = MagicMock()
    client.with_structured_output.side_effect = NotImplementedError
    client.invoke.return_value = type("R", (), {"content": content})()

    def one(*args, **kwargs):
        yield Provider.GEMINI, client

    with patch("ai_workflows.harness.contract.get_models",
               side_effect=one) as get:
        yield get


class _FakeSchema(AgentOutput):
    confidence_level: float = 0.0
    sanitized_text: str = ""


class RuntimeFailoverTests(TestCase):
    """Failover that covers a provider going down mid-call, not just at build.

    The live eval run is what exposed the gap: Gemini's free tier ran out of
    quota, every case died, and nothing tried the next provider -- because a
    429 arrives when the model is *invoked*, long after `get_model` handed back
    a perfectly well-constructed client.
    """

    # These measure moving between providers. Waiting out a refusal that
    # clears on its own is a separate question, answered in test_retrying --
    # and left on, every 429 below would be slept off for real.
    def setUp(self):
        _provider("gemini", preference=10, model="g")
        _provider("openai", preference=60, model="o")

    def _clients(self, first, second):
        """Two candidate clients, in preference order."""
        def iterator(*args, **kwargs):
            yield Provider.GEMINI, first
            if kwargs.get("allow_fallback", True):
                yield Provider.OPENAI, second

        return patch("ai_workflows.harness.contract.get_models", side_effect=iterator)

    @staticmethod
    def _client(content=None, error=None):
        client = MagicMock()
        client.with_structured_output.side_effect = NotImplementedError
        if error is not None:
            client.invoke.side_effect = error
        else:
            client.invoke.return_value = type("R", (), {"content": content})()
        return client

    def test_a_rate_limited_provider_falls_over_to_the_next(self):
        from ai_workflows.harness.contract import ask

        exhausted = self._client(error=RuntimeError("429 RESOURCE_EXHAUSTED"))
        working = self._client('{"sanitized_text": "written"}')

        with self._clients(exhausted, working):
            result = ask(None, "do it", _FakeSchema, agent="writer", policy=NEVER)

        self.assertEqual(result.sanitized_text, "written")
        self.assertTrue(exhausted.invoke.called)

    def test_an_agent_that_must_not_drift_fails_instead(self):
        """The verifier's verdicts are compared across runs. Surviving an
        outage by quietly answering on a different model would make the
        comparison meaningless, which is worse than the outage."""
        from ai_workflows.harness.contract import ask

        exhausted = self._client(error=RuntimeError("429 RESOURCE_EXHAUSTED"))
        working = self._client('{"sanitized_text": "written"}')

        with self._clients(exhausted, working):
            with self.assertRaises(ModelUnavailable):
                ask(None, "check it", _FakeSchema, agent="fact_verifier",
                    allow_fallback=False, policy=NEVER)

        self.assertFalse(working.invoke.called)

    def test_a_call_failure_is_reported_as_the_provider_failing(self):
        """It used to be reported as an invalid shape, which sent whoever read
        the alert looking for a malformed response that did not exist."""
        from ai_workflows.harness.contract import ask

        exhausted = self._client(error=RuntimeError("429 RESOURCE_EXHAUSTED"))

        def only_one(*args, **kwargs):
            yield Provider.GEMINI, exhausted

        with patch("ai_workflows.harness.contract.get_models", side_effect=only_one):
            with self.assertRaises(ModelUnavailable) as caught:
                ask(None, "do it", _FakeSchema, agent="writer", policy=NEVER)

        self.assertIn("429", str(caught.exception))

    def test_a_shape_failure_does_not_change_provider(self):
        """Another provider is no more likely to satisfy a schema the first one
        misread, and swapping would hide which model produced the bad shape."""
        from ai_workflows.harness.contract import ask
        from ai_workflows.harness.errors import AgentOutputInvalid

        malformed = self._client("not json at all")
        working = self._client('{"sanitized_text": "written"}')

        with self._clients(malformed, working):
            with self.assertRaises(AgentOutputInvalid):
                ask(None, "do it", _FakeSchema, agent="writer", retries=0)

        self.assertFalse(working.invoke.called)

    def test_an_explicit_model_is_used_as_given(self):
        """A caller that passed a model has already chosen; failing over would
        make the choice meaningless."""
        from ai_workflows.harness.contract import ask

        given = self._client('{"sanitized_text": "written"}')
        with patch("ai_workflows.harness.contract.get_models") as candidates:
            result = ask(None, "do it", _FakeSchema, model=given)

        self.assertEqual(result.sanitized_text, "written")
        candidates.assert_not_called()
