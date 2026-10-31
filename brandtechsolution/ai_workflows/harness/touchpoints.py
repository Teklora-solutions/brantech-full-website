"""Touchpoint registry and auto-discovery for AI LLM invocation points.

A touchpoint is any point in the Django codebase that invokes an LLM.
By decorating agents, views, or tasks with `@register_touchpoint` or passing
`touchpoint="key"` to `get_model()`, touchpoints are auto-registered and kept
synchronized with the database `AITouchpoint` table.

Admins can pin specific providers and models per touchpoint in the AI Configuration
hub, enabling fine-grained model routing without hardcoding model names.
"""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# In-memory registry of touchpoint definitions discovered across code
_TOUCHPOINT_DEFINITIONS = {}


@dataclass
class TouchpointDef:
    key: str
    name: str
    description: str
    default_role: str = "analytic"


def register_touchpoint(key: str, name: str = "", description: str = "", default_role: str = "analytic"):
    """Decorator or function to register an AI touchpoint.

    Usage as a decorator:
        @register_touchpoint("writer", name="Article Writer", description="Drafts blog posts", default_role="creative")
        class WriterAgent(Agent):
            ...

    Usage as a function call:
        register_touchpoint("chat_assistant", name="Chat Assistant", default_role="conversational")
    """
    def decorator(target):
        def_name = name or key.replace("_", " ").title()
        doc = description or (getattr(target, "__doc__", "") or "").strip().split("\n")[0]
        _TOUCHPOINT_DEFINITIONS[key] = TouchpointDef(
            key=key,
            name=def_name,
            description=doc,
            default_role=default_role,
        )
        return target

    if callable(name):
        # Called as @register_touchpoint (without parens) - not standard here, but safe
        target = name
        return decorator(target)

    # If called as regular function without decorating a target class
    if not isinstance(name, str):
        name = ""
    def_name = name or key.replace("_", " ").title()
    _TOUCHPOINT_DEFINITIONS[key] = TouchpointDef(
        key=key,
        name=def_name,
        description=description,
        default_role=default_role,
    )
    return decorator


def get_touchpoint_def(key: str) -> Optional[TouchpointDef]:
    """Retrieve an in-memory touchpoint definition by key."""
    return _TOUCHPOINT_DEFINITIONS.get(key)


def get_or_create_touchpoint_row(key: str, *, name: str = "", description: str = "", default_role: str = "analytic"):
    """Get or auto-create the AITouchpoint database row."""
    from ai_workflows.models import AITouchpoint

    defn = _TOUCHPOINT_DEFINITIONS.get(key)
    target_name = name or (defn.name if defn else key.replace("_", " ").title())
    target_desc = description or (defn.description if defn else "")
    target_role = default_role or (defn.default_role if defn else "analytic")

    row, created = AITouchpoint.objects.get_or_create(
        key=key,
        defaults={
            "name": target_name,
            "description": target_desc,
            "default_role": target_role,
        },
    )
    if not created and (defn and (row.name != defn.name or row.description != defn.description)):
        # Keep descriptions updated if code definitions evolve
        if defn.description and not row.description:
            row.description = defn.description
            row.save(update_fields=["description"])

    return row


def record_touchpoint_invocation(key: str):
    """Update invocation count and timestamp for a touchpoint."""
    from django.utils import timezone
    from ai_workflows.models import AITouchpoint

    AITouchpoint.objects.filter(key=key).update(
        total_invocations=models_f_expr(),
        last_invoked_at=timezone.now(),
    )


def models_f_expr():
    from django.db.models import F
    return F("total_invocations") + 1


def sync_registered_touchpoints():
    """Sync all in-memory touchpoint definitions with the database."""
    from ai_workflows.models import AITouchpoint

    synced = []
    for key, defn in _TOUCHPOINT_DEFINITIONS.items():
        row, _ = AITouchpoint.objects.update_or_create(
            key=key,
            defaults={
                "name": defn.name,
                "description": defn.description,
                "default_role": defn.default_role,
            },
        )
        synced.append(row)
    return synced


# Register standard built-in Teklora touchpoints upfront:
register_touchpoint(
    key="assistant",
    name="Conversational Chatbot",
    description="Interactive customer assistant answering inquiries and guiding users.",
    default_role="conversational",
)
register_touchpoint(
    key="writer",
    name="Editorial Article Writer",
    description="Drafts long-form, authoritative tech journalism and enterprise blog articles.",
    default_role="creative",
)
register_touchpoint(
    key="fact_verifier",
    name="Fact Verifier & Citation Auditor",
    description="Audits factual claims against live web sources and knowledge base vectors.",
    default_role="precise",
)
register_touchpoint(
    key="research",
    name="Deep Web & Domain Researcher",
    description="Conducts multi-angle information retrieval and market analysis.",
    default_role="analytic",
)
register_touchpoint(
    key="trend_intelligence",
    name="Trend Intelligence Evaluator",
    description="Discovers, scores, and prioritizes breaking technology developments.",
    default_role="analytic",
)
register_touchpoint(
    key="trend_prediction",
    name="Trend Forecasting Agent",
    description="Forecasts technological trajectories, business impacts, and market adoption.",
    default_role="analytic",
)
register_touchpoint(
    key="social",
    name="Multi-Platform Social Syndicator",
    description="Adapts published articles into platform-optimized social posts (LinkedIn, Twitter, Threads).",
    default_role="creative",
)
register_touchpoint(
    key="newsroom",
    name="Automated Editorial Newsroom",
    description="Full supervisor cycle orchestrating intelligence, research, drafting, verification, and syndication.",
    default_role="analytic",
)
