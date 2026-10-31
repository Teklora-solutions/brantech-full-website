"""Step 3: providers, activation, and the model catalogue.

Every provider call is stubbed. The suite must not reach a vendor and must not
need five API keys to run -- a test that silently passes because a key happened
to be present is not a test.
"""
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from ai_workflows.harness.catalogue import (
    apply_manual_prices,
    borrow_openrouter_prices,
    load_manual_prices,
    refresh,
    resolve,
    sync_provider,
)
from ai_workflows.harness.providers import (
    ADAPTERS,
    AnthropicAdapter,
    GeminiAdapter,
    ModelInfo,
    OpenRouterAdapter,
    get_adapter,
)
from ai_workflows.models import CatalogueEntry, Provider


class StubAdapter:
    """Stands in for a provider without touching the network."""

    billing = "usage"
    preference = 100
    default_enabled = True

    def __init__(self, name, models=None, credential="key", publishes_pricing=False,
                 raises=None):
        self.name = name
        self._models = models or []
        self._credential = credential
        self.publishes_pricing = publishes_pricing
        self._raises = raises
        self.list_calls = 0

    def credential(self):
        return self._credential

    def has_credential(self):
        return bool(self._credential)

    def list_models(self):
        self.list_calls += 1
        if self._raises:
            raise self._raises
        return self._models


class AdapterShapeTests(TestCase):
    """Each adapter knows its own endpoint and response shape."""

    def test_every_adapter_is_addressable_by_name(self):
        for name in ("gemini", "vertex", "openrouter", "anthropic", "openai", "deepseek", "codex"):
            self.assertIs(get_adapter(name), ADAPTERS[name])

    def test_an_unknown_provider_lists_the_known_ones(self):
        with self.assertRaises(KeyError) as caught:
            get_adapter("nope")
        self.assertIn("gemini", str(caught.exception))

    def test_openrouter_is_the_only_one_publishing_pricing(self):
        """The finding that shapes the whole module."""
        publishing = [n for n, a in ADAPTERS.items() if a.publishes_pricing]
        self.assertEqual(publishing, ["openrouter"])

    def test_codex_is_subscription_billed_and_off_by_default(self):
        codex = ADAPTERS["codex"]
        self.assertEqual(codex.billing, "subscription")
        self.assertFalse(codex.default_enabled)

    def test_openrouter_prices_convert_from_per_token_to_per_million(self):
        info = OpenRouterAdapter._parse({
            "id": "vendor/model",
            "name": "Vendor: Model",
            "context_length": 262144,
            "pricing": {"prompt": "0.000000075", "completion": "0.0000005"},
            "top_provider": {"max_completion_tokens": 32768},
            "architecture": {"modality": "text->text"},
            "expiration_date": "2026-12-31",
        })
        self.assertAlmostEqual(info.input_price_per_mtok, 0.075)
        self.assertAlmostEqual(info.output_price_per_mtok, 0.5)
        self.assertEqual(info.context_tokens, 262144)
        self.assertEqual(info.max_output_tokens, 32768)

    def test_a_model_without_pricing_is_unpriced_not_free(self):
        info = OpenRouterAdapter._parse({"id": "vendor/model", "pricing": {}})
        self.assertIsNone(info.input_price_per_mtok)

    def test_anthropic_uses_max_input_tokens_not_context_window(self):
        """There is no context_window field on that API."""
        with patch.object(AnthropicAdapter, "_get", return_value={"data": [{
            "id": "claude-opus-5", "display_name": "Claude Opus 5",
            "max_input_tokens": 1_000_000, "max_tokens": 128_000,
        }]}), patch.object(AnthropicAdapter, "credential", return_value="k"):
            info = AnthropicAdapter().list_models()[0]

        self.assertEqual(info.context_tokens, 1_000_000)
        self.assertEqual(info.max_output_tokens, 128_000)
        self.assertIsNone(info.input_price_per_mtok)  # that API carries no price

    def test_gemini_keeps_the_models_prefix_it_returns(self):
        with patch.object(GeminiAdapter, "_get", return_value={"models": [{
            "name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash",
            "inputTokenLimit": 1_048_576, "outputTokenLimit": 65_536,
            "supportedGenerationMethods": ["generateContent"],
        }]}), patch.object(GeminiAdapter, "credential", return_value="k"):
            info = GeminiAdapter().list_models()[0]

        self.assertEqual(info.model_id, "models/gemini-2.5-flash")
        self.assertEqual(info.context_tokens, 1_048_576)


class ActivationTests(TestCase):
    """Three states, because a key being present is not a key working."""

    def test_no_credential_is_absent_without_a_network_call(self):
        adapter = StubAdapter("demo", credential="")
        provider = sync_provider("demo", adapter=adapter)

        self.assertEqual(provider.status, Provider.ABSENT)
        self.assertEqual(adapter.list_calls, 0)

    def test_a_working_credential_becomes_active(self):
        adapter = StubAdapter("demo", models=[ModelInfo(model_id="m1")])
        provider = sync_provider("demo", adapter=adapter)

        self.assertEqual(provider.status, Provider.ACTIVE)
        self.assertEqual(provider.last_error, "")
        self.assertIsNotNone(provider.last_checked_at)

    def test_a_rejected_credential_stays_candidate_with_the_reason(self):
        """A bad key must be visible, not silent."""
        adapter = StubAdapter("demo", raises=RuntimeError("401 Unauthorized"))
        provider = sync_provider("demo", adapter=adapter)

        self.assertEqual(provider.status, Provider.CANDIDATE)
        self.assertIn("401", provider.last_error)

    def test_recovery_clears_the_error(self):
        sync_provider("demo", adapter=StubAdapter("demo", raises=RuntimeError("down")))
        provider = sync_provider("demo", adapter=StubAdapter(
            "demo", models=[ModelInfo(model_id="m1")]))

        self.assertEqual(provider.status, Provider.ACTIVE)
        self.assertEqual(provider.last_error, "")

    def test_a_disabled_provider_is_not_usable_even_when_active(self):
        sync_provider("demo", adapter=StubAdapter("demo", models=[ModelInfo(model_id="m")]))
        Provider.objects.filter(name="demo").update(enabled=False)

        self.assertFalse(Provider.objects.get(name="demo").usable)


class CatalogueTests(TestCase):
    def test_models_are_recorded_with_their_metadata(self):
        sync_provider("demo", adapter=StubAdapter("demo", models=[
            ModelInfo(model_id="m1", display_name="Model One",
                      context_tokens=100_000, max_output_tokens=8_000),
        ]))
        entry = CatalogueEntry.objects.get(provider="demo", model_id="m1")

        self.assertEqual(entry.display_name, "Model One")
        self.assertEqual(entry.context_tokens, 100_000)
        self.assertTrue(entry.available)

    def test_a_vanished_model_is_marked_gone_not_deleted(self):
        """Invocation rows point at it; history must not rewrite itself."""
        sync_provider("demo", adapter=StubAdapter("demo", models=[
            ModelInfo(model_id="old"), ModelInfo(model_id="kept"),
        ]))
        sync_provider("demo", adapter=StubAdapter("demo", models=[ModelInfo(model_id="kept")]))

        self.assertFalse(CatalogueEntry.objects.get(model_id="old").available)
        self.assertTrue(CatalogueEntry.objects.get(model_id="kept").available)
        self.assertEqual(CatalogueEntry.objects.count(), 2)

    def test_a_provider_that_publishes_pricing_sets_it_as_authoritative(self):
        sync_provider("router", adapter=StubAdapter("router", publishes_pricing=True, models=[
            ModelInfo(model_id="m1", input_price_per_mtok=1.0, output_price_per_mtok=2.0),
        ]))
        entry = CatalogueEntry.objects.get(model_id="m1")

        self.assertEqual(entry.price_source, CatalogueEntry.PROVIDER)
        self.assertTrue(entry.price_is_authoritative)

    def test_a_provider_that_does_not_leaves_the_price_unknown(self):
        sync_provider("demo", adapter=StubAdapter("demo", models=[ModelInfo(model_id="m1")]))
        entry = CatalogueEntry.objects.get(model_id="m1")

        self.assertEqual(entry.price_source, CatalogueEntry.UNKNOWN)
        self.assertFalse(entry.price_is_known)

    def test_an_unpriced_model_costs_none_not_zero(self):
        """Reporting an unknown price as free understates every total it joins."""
        entry = CatalogueEntry.objects.create(provider="demo", model_id="m")
        self.assertIsNone(entry.cost_for(1000, 500))

    def test_a_priced_model_computes_its_cost(self):
        entry = CatalogueEntry.objects.create(
            provider="demo", model_id="m",
            input_price_per_mtok=3, output_price_per_mtok=15,
            price_source=CatalogueEntry.MANUAL,
        )
        # 1M prompt tokens at $3 + 1M completion at $15
        self.assertAlmostEqual(entry.cost_for(1_000_000, 1_000_000), 18.0)


class PricingProvenanceTests(TestCase):
    """price_source is the whole point: not every number is equally trustworthy."""

    def setUp(self):
        CatalogueEntry.objects.create(
            provider="openrouter", model_id="anthropic/claude-opus-5",
            input_price_per_mtok=5.5, output_price_per_mtok=27.5,
            price_source=CatalogueEntry.PROVIDER,
        )
        self.direct = CatalogueEntry.objects.create(
            provider="anthropic", model_id="claude-opus-5",
        )

    def test_a_direct_provider_borrows_the_price_its_api_omits(self):
        self.assertEqual(borrow_openrouter_prices(), 1)

        self.direct.refresh_from_db()
        self.assertEqual(float(self.direct.input_price_per_mtok), 5.5)
        self.assertEqual(self.direct.price_source, CatalogueEntry.OPENROUTER)

    def test_a_borrowed_price_is_not_authoritative(self):
        """OpenRouter's price is what OpenRouter charges to proxy the model."""
        borrow_openrouter_prices()
        self.direct.refresh_from_db()
        self.assertFalse(self.direct.price_is_authoritative)

    def test_the_manual_table_beats_a_borrowed_price(self):
        borrow_openrouter_prices()
        applied = apply_manual_prices(
            {"anthropic": {"claude-opus-5": {"input": 5.0, "output": 25.0,
                                             "as_of": "2026-06-24"}}}
        )

        self.assertEqual(applied, 1)
        self.direct.refresh_from_db()
        self.assertEqual(float(self.direct.input_price_per_mtok), 5.0)
        self.assertEqual(self.direct.price_source, CatalogueEntry.MANUAL)
        self.assertTrue(self.direct.price_is_authoritative)

    def test_a_gemini_models_prefix_still_matches(self):
        CatalogueEntry.objects.create(
            provider="openrouter", model_id="google/gemini-2.5-flash",
            input_price_per_mtok=0.3, output_price_per_mtok=2.5,
            price_source=CatalogueEntry.PROVIDER,
        )
        gemini = CatalogueEntry.objects.create(
            provider="gemini", model_id="models/gemini-2.5-flash")

        borrow_openrouter_prices()
        gemini.refresh_from_db()
        self.assertEqual(float(gemini.input_price_per_mtok), 0.3)


class ManualPriceFileTests(TestCase):
    def test_the_checked_in_table_parses(self):
        prices = load_manual_prices()
        self.assertIn("anthropic", prices)
        self.assertIn("claude-opus-5", prices["anthropic"])

    def test_every_listed_provider_carries_an_as_of_date(self):
        """An undated price cannot be told from a checked one when it is read."""
        for provider, models in load_manual_prices().items():
            for model_id, values in models.items():
                self.assertIsNotNone(values.get("as_of"), f"{provider}/{model_id}")

    def test_an_undated_block_is_ignored_rather_than_trusted(self):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write('[sketchy]\n[sketchy.models]\n"m" = { input = 1.0 }\n')
            path = Path(handle.name)

        self.assertEqual(load_manual_prices(path), {})


class ResolutionTests(TestCase):
    """`resolve` dropped its unused `role` argument when it learned to pick a
    model: role decides temperature, not which model answers.

    Each provider needs a chosen model and a credential to qualify, so both are
    supplied here. What each of those conditions does on its own is covered in
    test_multiprovider.
    """

    def setUp(self):
        for name, preference in (("gemini", 10), ("openrouter", 50)):
            Provider.objects.create(
                name=name, status=Provider.ACTIVE, preference=preference,
                default_model=f"{name}-model",
            )
            CatalogueEntry.objects.create(provider=name, model_id=f"{name}-model")

        serving = patch("ai_workflows.harness.catalogue.can_serve", lambda n: True)
        serving.start()
        self.addCleanup(serving.stop)

    def test_the_preferred_provider_comes_first(self):
        self.assertEqual(resolve()[0][0], "gemini")

    def test_an_explicit_pin_wins(self):
        pinned = ("anthropic", "claude-opus-5")
        self.assertEqual(resolve(pinned=pinned), [pinned])

    def test_fallback_offers_every_usable_provider(self):
        self.assertEqual(len(resolve()), 2)

    def test_refusing_fallback_offers_only_one(self):
        """A verifier compared across runs must not change model silently."""
        self.assertEqual(len(resolve(allow_fallback=False)), 1)

    def test_an_inactive_provider_is_skipped(self):
        Provider.objects.filter(name="gemini").update(status=Provider.CANDIDATE)
        self.assertEqual(resolve()[0][0], "openrouter")

    def test_a_disabled_provider_is_skipped(self):
        Provider.objects.filter(name="gemini").update(enabled=False)
        self.assertEqual(resolve()[0][0], "openrouter")


class RefreshTests(TestCase):
    def test_refresh_visits_every_provider(self):
        stubs = {name: StubAdapter(name, models=[ModelInfo(model_id=f"{name}-m")])
                 for name in ADAPTERS}

        with patch("ai_workflows.harness.catalogue.get_adapter", stubs.get):
            result = refresh()

        self.assertEqual(set(result["providers"]), set(ADAPTERS))
        self.assertEqual(
            Provider.objects.filter(status=Provider.ACTIVE).count(), len(ADAPTERS)
        )


class SystemCheckTests(TestCase):
    def test_a_configured_provider_reports_nothing(self):
        from ai_workflows.checks import check_providers

        self.assertEqual(check_providers(None), [])

    def test_no_provider_at_all_is_reported(self):
        from ai_workflows.checks import check_providers

        with patch.dict(
            "ai_workflows.harness.providers.ADAPTERS",
            {name: StubAdapter(name, credential="") for name in ADAPTERS},
            clear=True,
        ):
            messages = check_providers(None)

        self.assertTrue(messages)
        self.assertIn("W001", messages[0].id)  # a warning under DEBUG/TESTING


class CommandTests(TestCase):
    def test_the_command_reports_provider_status(self):
        stubs = {name: StubAdapter(name, credential="") for name in ADAPTERS}
        out = StringIO()

        with patch("ai_workflows.harness.catalogue.get_adapter", stubs.get):
            call_command("refresh_catalogue", stdout=out)

        printed = out.getvalue()
        self.assertIn("gemini", printed)
        self.assertIn("absent", printed)
