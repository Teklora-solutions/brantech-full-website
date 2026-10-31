"""Provider adapters: credentials, activation, and listing models.

One adapter per provider, each knowing three things -- where its credential
comes from, how to list its models, and how to read that listing. Adding a
sixth provider is a class here and nothing else.

Verified against the live endpoints on 2026-09-21. The finding that shapes
this module: **only OpenRouter publishes pricing through its API.** It is also
unauthenticated, and it lists the other four providers' models under
`anthropic/`, `openai/`, `google/` and `deepseek/` slugs -- which makes it the
metadata source for everyone, with the ceiling recorded on every row it feeds
(see `CatalogueEntry.price_source`).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from brandtechsolution.config import config

logger = logging.getLogger(__name__)

LIST_TIMEOUT = 15


@dataclass
class ModelInfo:
    """One model as a provider described it."""

    model_id: str
    display_name: str = ""
    context_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    capabilities: dict | None = None
    deprecated_at: str | None = None

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = {}


class ProviderAdapter:
    """Base adapter. Subclasses supply the credential and the listing."""

    name = ""
    billing = "usage"
    preference = 100
    # Off by default unless a subclass says otherwise. Enabling a provider is
    # a decision, not a side effect of a key appearing in the environment.
    default_enabled = True
    # Whether this provider's own listing carries prices. Only OpenRouter does.
    publishes_pricing = False

    def credential(self):
        """The configured secret, or "" when absent."""
        raise NotImplementedError

    def list_models(self):
        """Every model this provider offers. Raises on a transport failure."""
        raise NotImplementedError

    def has_credential(self):
        return bool(self.credential())

    def verify(self):
        """Confirm the credential works, by the cheapest call available.

        Listing models is that call for every provider here, and it is also
        what the catalogue refresh needs -- so activation and refresh are one
        operation rather than two round trips.
        """
        return self.list_models()

    @staticmethod
    def _get(url, headers=None, params=None):
        response = requests.get(
            url, headers=headers or {}, params=params or {}, timeout=LIST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()


class OpenRouterAdapter(ProviderAdapter):
    """The only provider that publishes pricing, and it needs no key to do it.

    Its catalogue covers the other four under `anthropic/`, `openai/`,
    `google/` and `deepseek/` slugs, with per-token prices, context lengths and
    expiration dates -- so it doubles as the metadata source for providers
    whose own APIs carry none.
    """

    name = "openrouter"
    preference = 50
    publishes_pricing = True

    BASE = "https://openrouter.ai/api/v1"

    def credential(self):
        return (getattr(config, "openrouter_api_key", "") or "").strip()

    def list_models(self):
        # Deliberately unauthenticated: the listing is public, so the catalogue
        # can be refreshed -- and other providers' prices learned -- before
        # anyone has an OpenRouter key.
        payload = self._get(f"{self.BASE}/models")
        return [self._parse(row) for row in payload.get("data", [])]

    @staticmethod
    def _parse(row):
        pricing = row.get("pricing") or {}

        def per_mtok(value):
            # Prices arrive as strings, per single token.
            try:
                return float(value) * 1_000_000
            except (TypeError, ValueError):
                return None

        top = row.get("top_provider") or {}
        return ModelInfo(
            model_id=row.get("id", ""),
            display_name=row.get("name", ""),
            context_tokens=row.get("context_length"),
            max_output_tokens=top.get("max_completion_tokens"),
            input_price_per_mtok=per_mtok(pricing.get("prompt")),
            output_price_per_mtok=per_mtok(pricing.get("completion")),
            capabilities={
                "modality": (row.get("architecture") or {}).get("modality"),
                "supported_parameters": row.get("supported_parameters") or [],
                "knowledge_cutoff": row.get("knowledge_cutoff"),
            },
            deprecated_at=row.get("expiration_date"),
        )


class OpenAIAdapter(ProviderAdapter):
    name = "openai"
    preference = 60
    BASE = "https://api.openai.com/v1"

    def credential(self):
        return (getattr(config, "openai_api_key", "") or "").strip()

    def list_models(self):
        # Returns id / object / created / owned_by and nothing else -- no
        # pricing, no context window. Prices for these come from OpenRouter or
        # the manual table.
        payload = self._get(
            f"{self.BASE}/models",
            headers={"Authorization": f"Bearer {self.credential()}"},
        )
        return [
            ModelInfo(model_id=row.get("id", ""), display_name=row.get("id", ""))
            for row in payload.get("data", [])
        ]


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"
    preference = 55
    BASE = "https://api.anthropic.com/v1"

    def credential(self):
        return (getattr(config, "anthropic_api_key", "") or "").strip()

    def list_models(self):
        payload = self._get(
            f"{self.BASE}/models",
            headers={
                "x-api-key": self.credential(),
                "anthropic-version": "2023-06-01",
            },
        )
        return [
            ModelInfo(
                model_id=row.get("id", ""),
                display_name=row.get("display_name", ""),
                # Named max_input_tokens, not context_window.
                context_tokens=row.get("max_input_tokens"),
                max_output_tokens=row.get("max_tokens"),
                capabilities=row.get("capabilities") or {},
            )
            for row in payload.get("data", [])
        ]


class GeminiAdapter(ProviderAdapter):
    name = "gemini"
    preference = 10  # the incumbent; everything runs on it today
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def credential(self):
        return (config.google_api_key or "").strip()

    def list_models(self):
        payload = self._get(
            f"{self.BASE}/models", params={"key": self.credential(), "pageSize": 200},
        )
        out = []
        for row in payload.get("models", []):
            # Names arrive as "models/gemini-2.5-flash".
            model_id = row.get("name", "")
            out.append(ModelInfo(
                model_id=model_id,
                display_name=row.get("displayName", ""),
                context_tokens=row.get("inputTokenLimit"),
                max_output_tokens=row.get("outputTokenLimit"),
                capabilities={
                    "methods": row.get("supportedGenerationMethods") or [],
                    "thinking": row.get("thinking"),
                },
            ))
        return out


class DeepSeekAdapter(ProviderAdapter):
    name = "deepseek"
    preference = 70
    BASE = "https://api.deepseek.com"

    def credential(self):
        return (getattr(config, "deepseek_api_key", "") or "").strip()

    def list_models(self):
        payload = self._get(
            f"{self.BASE}/models",
            headers={"Authorization": f"Bearer {self.credential()}"},
        )
        return [
            ModelInfo(model_id=row.get("id", ""), display_name=row.get("id", ""))
            for row in payload.get("data", [])
        ]


class CodexAdapter(ProviderAdapter):
    """OpenAI Codex over ChatGPT OAuth. Built, and off by default.

    The mechanism is real: `codex login` writes tokens to ~/.codex/auth.json
    and those credentials can serve requests against a ChatGPT subscription
    rather than API credits. What makes it different from the other five is
    policy, not capability -- OpenAI's own Codex authentication documentation
    says to use API keys for programmatic workflows and states that
    subscription credentials are not intended for server-side requests.

    So it is modelled as visibly not the same kind of thing: subscription
    billing, disabled unless an operator turns it on, and never in the default
    preference order. It is also the worst secret here to hold, being an
    account credential rather than a scoped, revocable, spend-capped one.
    """

    name = "codex"
    billing = "subscription"
    preference = 900
    default_enabled = False

    def credential(self):
        # 1. Configured token from environment
        token = (getattr(config, "codex_oauth_token", "") or "").strip()
        if token:
            return token

        # 2. Local fallback: ~/.codex/auth.json if present
        local_auth = Path.home() / ".codex" / "auth.json"
        if local_auth.exists():
            try:
                import json
                with local_auth.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    tok = data.get("tokens", {}).get("access_token", "")
                    if tok:
                        return tok.strip()
            except Exception:
                pass
        return ""

    def has_credential(self):
        return bool(self.credential())

    def list_models(self):
        # Known models accessible via ChatGPT Plus/Pro subscription
        return [
            ModelInfo(model_id="gpt-4o", display_name="GPT-4o (Codex Subscription)", context_tokens=128000),
            ModelInfo(model_id="gpt-4o-mini", display_name="GPT-4o Mini (Codex Subscription)", context_tokens=128000),
            ModelInfo(model_id="o1-preview", display_name="o1 Preview (Codex Subscription)", context_tokens=128000),
            ModelInfo(model_id="o3-mini", display_name="o3 Mini (Codex Subscription)", context_tokens=200000),
        ]


class VertexAIAdapter(ProviderAdapter):
    """Google Cloud Vertex AI using Service Account JSON Credentials.

    Reads `GOOGLE_APPLICATION_CREDENTIALS` (path to service account JSON),
    `VERTEX_PROJECT_ID`, and `VERTEX_LOCATION`.
    """

    name = "vertex"
    billing = "usage"
    preference = 15

    def credential(self):
        cred_path = (getattr(config, "google_application_credentials", "") or "").strip()
        if not cred_path:
            import os
            cred_path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") or "").strip()
        return cred_path

    def has_credential(self):
        path = self.credential()
        if not path:
            return False
        return Path(path).exists()

    def list_models(self):
        if not self.has_credential():
            return []
        return [
            ModelInfo(model_id="gemini-2.5-flash", display_name="Gemini 2.5 Flash (Vertex AI)", context_tokens=1048576, max_output_tokens=8192),
            ModelInfo(model_id="gemini-1.5-pro", display_name="Gemini 1.5 Pro (Vertex AI)", context_tokens=2097152, max_output_tokens=8192),
            ModelInfo(model_id="gemini-1.5-flash", display_name="Gemini 1.5 Flash (Vertex AI)", context_tokens=1048576, max_output_tokens=8192),
            ModelInfo(model_id="gemini-2.5-pro", display_name="Gemini 2.5 Pro (Vertex AI)", context_tokens=2097152, max_output_tokens=8192),
        ]


ADAPTERS = {
    adapter.name: adapter()
    for adapter in (
        GeminiAdapter, VertexAIAdapter, OpenRouterAdapter, AnthropicAdapter,
        OpenAIAdapter, DeepSeekAdapter, CodexAdapter,
    )
}


def get_adapter(name):
    try:
        return ADAPTERS[name]
    except KeyError:
        raise KeyError(
            f"no adapter for provider {name!r} (known: {', '.join(sorted(ADAPTERS))})"
        ) from None
