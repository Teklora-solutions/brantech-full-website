"""Model access: the only file in the codebase that names a vendor.

Six agents used to build their own `ChatGoogleGenerativeAI`, differing only in
temperature, each wrapped in a try/except that set `self.model = None`. That is
gone; what is here is the one place a chat client is constructed.

Roles rather than raw temperatures. The six values in use were really four
intentions, and naming the intention means a future model swap re-tunes in one
place instead of six -- 0.4 is not a fact about the writer, it is a guess about
Gemini that will be wrong for the next model.

**Which model, and which provider.** Step 3 built the catalogue: six adapters,
activation states, and 500-odd models with prices. Until now none of that
reached `get_model`, which could only ever build a Gemini client -- so adding an
OpenAI key activated a provider that could not serve a request. This module is
the other half.

Two rules that between them keep it honest:

- **A provider must have a model chosen for it.** Picking one out of a
  five-hundred-row catalogue by heuristic is the kind of silent guess this
  whole harness exists to remove, and a wrong guess looks exactly like a right
  one. A provider with a working key and no chosen model is skipped, loudly.
  Gemini is pre-chosen from `config.gemini_chat_model`, so nothing changes for
  the deployment that exists today.
- **Failover is opt-out, per agent.** Most agents should survive a provider
  outage by using the next one. An agent whose output is compared across runs
  -- the verifier, a grader -- must not, because a silent model swap
  mid-comparison makes a change in score unattributable. `Agent.allow_fallback`
  is threaded all the way here rather than being a flag nobody reads.
"""
import logging
from enum import Enum

from brandtechsolution.config import config

from ai_workflows.harness.errors import ModelUnavailable

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    """What a call needs from a model, not how to get it."""

    PRECISE = "precise"            # verification, extraction: be literal
    ANALYTIC = "analytic"          # scoring, research: reason, do not embellish
    CREATIVE = "creative"          # drafting, social: write something readable
    CONVERSATIONAL = "conversational"  # the assistant


# Tuned to match what the agents used before the harness, so adopting it was
# not also a silent change in behaviour: verifier 0.1, intelligence 0.2,
# research 0.3, writer and social 0.4.
ROLE_TEMPERATURE = {
    ModelRole.PRECISE: 0.1,
    ModelRole.ANALYTIC: 0.25,
    ModelRole.CREATIVE: 0.4,
    ModelRole.CONVERSATIONAL: 0.4,
}


class Provider(str, Enum):
    GEMINI = "gemini"
    VERTEX = "vertex"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    CODEX = "codex"


# Providers that speak the OpenAI wire format, and where. Three vendors, one
# client class: DeepSeek and OpenRouter both document their endpoints as
# OpenAI-compatible, so giving each its own adapter class would be three copies
# of the same code differing by a URL.
OPENAI_COMPATIBLE = {
    Provider.OPENAI: None,  # the default endpoint
    Provider.DEEPSEEK: "https://api.deepseek.com/v1",
    Provider.OPENROUTER: "https://openrouter.ai/api/v1",
    Provider.CODEX: "https://chatgpt.com/backend-api/codex",
}

REQUEST_TIMEOUT = 60
# Transport failures are retried here rather than in each agent. Content
# failures are the contract's business, not the client's.
MAX_RETRIES = 2


def _credential(provider):
    """The configured secret for `provider`.

    Read through the adapter rather than from `config` again, so that where a
    credential comes from is defined once. The adapters already had to know
    this to verify a key; there is no reason for a second copy to drift from
    it.
    """
    from ai_workflows.harness.providers import get_adapter

    try:
        return get_adapter(provider.value).credential()
    except KeyError:
        return ""


def _require_credential(provider, model):
    secret = _credential(provider)
    if not secret:
        raise ModelUnavailable(
            f"no credential configured for {provider.value}",
            provider=provider.value, model=model,
        )
    return secret


def _vertex(role, tools, model, **overrides):
    from google.oauth2 import service_account
    from langchain_google_genai import ChatGoogleGenerativeAI
    import json
    import os

    cred_path = _require_credential(Provider.VERTEX, model)
    credentials = None
    project_id = getattr(config, "vertex_project_id", "")
    location = getattr(config, "vertex_location", "global")

    if cred_path and os.path.exists(cred_path):
        credentials = service_account.Credentials.from_service_account_file(cred_path)
        if not project_id:
            try:
                with open(cred_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    project_id = data.get("project_id", "")
            except Exception:
                pass

    kwargs = {
        "model": model,
        "credentials": credentials,
        "vertexai": True,
        "project": project_id or None,
        "location": location,
        "temperature": ROLE_TEMPERATURE[role],
        "timeout": getattr(config, "llm_timeout", REQUEST_TIMEOUT),
        "max_retries": MAX_RETRIES,
    }
    kwargs.update(overrides)
    return _build(ChatGoogleGenerativeAI, kwargs, Provider.VERTEX, tools)


def _gemini(role, tools, model, **overrides):
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = {
        "model": model,
        "google_api_key": _require_credential(Provider.GEMINI, model),
        "temperature": ROLE_TEMPERATURE[role],
        "timeout": getattr(config, "llm_timeout", REQUEST_TIMEOUT),
        "max_retries": MAX_RETRIES,
    }
    kwargs.update(overrides)
    return _build(ChatGoogleGenerativeAI, kwargs, Provider.GEMINI, tools)


def _openai_compatible(provider):
    def builder(role, tools, model, **overrides):
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": model,
            "api_key": _require_credential(provider, model),
            "temperature": ROLE_TEMPERATURE[role],
            "timeout": getattr(config, "llm_timeout", REQUEST_TIMEOUT),
            "max_retries": MAX_RETRIES,
        }
        base_url = OPENAI_COMPATIBLE[provider]
        if base_url:
            kwargs["base_url"] = base_url
        kwargs.update(overrides)
        return _build(ChatOpenAI, kwargs, provider, tools)

    return builder


def _anthropic(role, tools, model, **overrides):
    from langchain_anthropic import ChatAnthropic

    kwargs = {
        "model": model,
        "api_key": _require_credential(Provider.ANTHROPIC, model),
        "temperature": ROLE_TEMPERATURE[role],
        "timeout": getattr(config, "llm_timeout", REQUEST_TIMEOUT),
        "max_retries": MAX_RETRIES,
        # Anthropic requires this; the others default it. Generous, because
        # the writer produces long articles and a truncated draft is a
        # confusing failure rather than an obvious one.
        "max_tokens": 8192,
    }
    kwargs.update(overrides)
    return _build(ChatAnthropic, kwargs, Provider.ANTHROPIC, tools)


def _build(client_class, kwargs, provider, tools):
    """Construct the client, converting any vendor error into ours.

    `ModelUnavailable` rather than a vendor exception, because the caller
    routes on our taxonomy and a provider-specific type leaking out would make
    every call site need to know which provider it got.
    """
    try:
        model = client_class(**kwargs)
    except ImportError as exc:
        raise ModelUnavailable(
            f"{provider.value} needs a package that is not installed: {exc}",
            provider=provider.value, model=kwargs.get("model"),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(
            f"could not build the {provider.value} client: {exc}",
            provider=provider.value, model=kwargs.get("model"),
        ) from exc

    return model.bind_tools(tools) if tools else model


_BUILDERS = {
    Provider.GEMINI: _gemini,
    Provider.VERTEX: _vertex,
    Provider.ANTHROPIC: _anthropic,
    **{p: _openai_compatible(p) for p in OPENAI_COMPATIBLE},
}


def iter_models(role=ModelRole.ANALYTIC, *, tools=None, provider=None, model=None,
                agent=None, touchpoint=None, allow_fallback=True, **overrides):
    """Yield (provider, client) for each candidate, building them lazily.

    `get_model` returns the first one that builds, which covers a provider that
    is misconfigured. It does not cover one that is *exhausted*: a 429 arrives
    when the model is invoked, long after it was constructed, so a caller
    holding a single client has nothing to fall back to.

    A caller that loops over this does. That is the difference between
    multi-provider meaning "you may choose one" and meaning "an outage does not
    stop the newsroom", and a rate limit is the most common outage there is.
    """
    role = ModelRole(role)
    tp_key = touchpoint or agent
    if tp_key:
        from ai_workflows.harness.touchpoints import (
            get_or_create_touchpoint_row,
            record_touchpoint_invocation,
        )
        try:
            tp_row = get_or_create_touchpoint_row(tp_key)
            if tp_row and not provider and tp_row.pinned_provider:
                provider = tp_row.pinned_provider
            if tp_row and not model and tp_row.pinned_model:
                model = tp_row.pinned_model
            if tp_row and tp_row.temperature_override is not None and "temperature" not in overrides:
                overrides["temperature"] = tp_row.temperature_override
            if tp_row and not tp_row.allow_fallback:
                allow_fallback = False
            record_touchpoint_invocation(tp_key)
        except Exception as exc:
            logger.debug("[llm] Touchpoint resolution notice: %s", exc)

    candidates = _candidates(
        provider=provider, model=model, allow_fallback=allow_fallback, agent=agent,
    )
    if not candidates:
        raise ModelUnavailable(
            "no provider is usable: none has a verified credential and a "
            "chosen model. Run `manage.py providers` to see why.",
            agent=agent,
        )

    failures = []
    for candidate_provider, candidate_model in candidates:
        builder = _BUILDERS.get(candidate_provider)
        if builder is None:
            failures.append(f"{candidate_provider.value}: no builder")
            continue

        try:
            client = builder(role, tools, candidate_model, **overrides)
        except ModelUnavailable as exc:
            exc.agent = exc.agent or agent
            if not allow_fallback:
                raise
            failures.append(f"{candidate_provider.value}: {exc}")
            logger.warning(
                "[llm] %s unusable for %s, trying the next provider: %s",
                candidate_provider.value, agent or role.value, exc,
            )
            continue

        yield candidate_provider, client

        # Control came back, so the caller rejected that client -- the call
        # failed at invoke time. Only keep offering alternatives if it is
        # allowed to drift.
        if not allow_fallback:
            return

    if not failures:
        return

    raise ModelUnavailable(
        "every candidate provider failed: " + "; ".join(failures), agent=agent,
    )


def get_model(role=ModelRole.ANALYTIC, *, tools=None, provider=None, model=None,
              agent=None, touchpoint=None, allow_fallback=True, **overrides):
    """A configured chat model for `role`.

    Raises `ModelUnavailable` rather than returning None. That is the whole
    point of this function existing: `self.model = None` is what let a missing
    API key turn into published fabrications instead of a failed run, and a
    return type that cannot express "absent" cannot be quietly ignored.

    With no explicit `provider`, candidates come from the catalogue in
    preference order and each is tried in turn. `allow_fallback=False` stops
    after the first, so an agent that must not drift between models does not.
    """
    role = ModelRole(role)
    tp_key = touchpoint or agent
    if tp_key:
        from ai_workflows.harness.touchpoints import (
            get_or_create_touchpoint_row,
            record_touchpoint_invocation,
        )
        try:
            tp_row = get_or_create_touchpoint_row(tp_key)
            if tp_row and not provider and tp_row.pinned_provider:
                provider = tp_row.pinned_provider
            if tp_row and not model and tp_row.pinned_model:
                model = tp_row.pinned_model
            if tp_row and tp_row.temperature_override is not None and "temperature" not in overrides:
                overrides["temperature"] = tp_row.temperature_override
            if tp_row and not tp_row.allow_fallback:
                allow_fallback = False
            record_touchpoint_invocation(tp_key)
        except Exception as exc:
            logger.debug("[llm] Touchpoint resolution notice: %s", exc)

    candidates = _candidates(
        provider=provider, model=model, allow_fallback=allow_fallback, agent=agent,
    )
    if not candidates:
        raise ModelUnavailable(
            "no provider is usable: none has a verified credential and a "
            "chosen model. Run `manage.py providers` to see why.",
            agent=agent,
        )

    failures = []
    for candidate_provider, candidate_model in candidates:
        builder = _BUILDERS.get(candidate_provider)
        if builder is None:
            failures.append(f"{candidate_provider.value}: no builder")
            continue

        try:
            return builder(role, tools, candidate_model, **overrides)
        except ModelUnavailable as exc:
            exc.agent = exc.agent or agent
            if not allow_fallback:
                raise
            # Labelled from the loop rather than from the exception. The
            # builders do set `provider`, but an aggregate error that depends
            # on every raiser having remembered to would eventually name the
            # wrong one -- and "every provider failed" is precisely the message
            # somebody reads at 3am.
            failures.append(f"{candidate_provider.value}: {exc}")
            logger.warning(
                "[llm] %s unusable for %s, trying the next provider: %s",
                candidate_provider.value, agent or role.value, exc,
            )

    raise ModelUnavailable(
        "every candidate provider failed: " + "; ".join(failures), agent=agent,
    )


def _candidates(*, provider, model, allow_fallback, agent):
    """(Provider, model_id) pairs to try, in order.

    An explicit provider is honoured as given -- a caller naming one is making
    a decision, and second-guessing it would make pinning meaningless. Without
    one, the catalogue answers.
    """
    if provider is not None:
        chosen = Provider(provider)
        return [(chosen, model or _configured_model(chosen, agent=agent))]

    from ai_workflows.harness.catalogue import resolve

    pairs = resolve(allow_fallback=allow_fallback)
    return [(Provider(name), model_id) for name, model_id in pairs]


def _configured_model(provider, *, agent=None):
    """The model chosen for `provider`, when a caller pinned the provider only."""
    from ai_workflows.harness.catalogue import chosen_model

    model = chosen_model(provider.value)
    if not model:
        raise ModelUnavailable(
            f"{provider.value} has no chosen model; set one with "
            f"`manage.py providers --set {provider.value}=<model-id>`",
            provider=provider.value, agent=agent,
        )
    return model


def get_embedder(*, provider=None, agent=None):
    """The embedding model.

    Resolved separately from `get_model`, and deliberately not multi-provider.
    Chat can fail over between providers mid-run without anyone noticing;
    embeddings cannot fail over at all, because a vector from another model is
    not merely differently sized -- it is meaningless in the same space as the
    stored ones. A deployment can run several providers for chat while
    embeddings stay on one, and losing the embedding provider degrades memory
    whatever else is configured.
    """
    provider = Provider(provider) if provider else Provider.GEMINI

    if provider is not Provider.GEMINI:
        raise ModelUnavailable(
            f"no embedding support for {provider.value}",
            provider=provider.value, agent=agent,
        )

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    if not config.google_api_key:
        raise ModelUnavailable(
            "GOOGLE_API_KEY is not set", provider=provider.value, agent=agent
        )

    try:
        return GoogleGenerativeAIEmbeddings(
            model=config.gemini_embedding_model,
            google_api_key=config.google_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailable(
            f"could not build the embedding client: {exc}",
            provider=provider.value,
            model=config.gemini_embedding_model,
            agent=agent,
        ) from exc
