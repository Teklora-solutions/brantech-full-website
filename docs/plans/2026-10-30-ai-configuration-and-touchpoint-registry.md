# Feature Specification & Execution Plan: Touchpoints Registry, AI Configuration Hub, Vertex AI, & Codex Device Auth

## 1. Overview
This feature introduces a comprehensive **AI Configuration & Touchpoint Governance Hub** into Teklora Admin (`/admin-panel/?section=ai`), providing:
1. **Touchpoint Auto-Registry Pattern (`ai_workflows/harness/touchpoints.py`)**: Any Django app or workflow requiring an LLM registers a touchpoint (e.g. `@register_touchpoint('writer', name='Editorial Article Writer', description='...', default_role='creative')`). When invoked or discovered across apps, it auto-registers/syncs into the database (`AITouchpoint` model) where admins can pin or override the specific Provider + Model + Fallback policy.
2. **Dynamic LLM Resolution with Touchpoint Override (`ai_workflows/harness/llm.py`)**: `get_model(..., touchpoint='writer')` checks if the touchpoint has an administrative override (e.g. Provider: `deepseek`, Model: `deepseek-chat`) before cascading to the global preference ladder.
3. **Vertex AI Adapter (`ai_workflows/harness/providers.py`)**:
   - Supports Google Cloud Service Account `.json` credentials via `GOOGLE_APPLICATION_CREDENTIALS` (or `VERTEX_CREDENTIALS_PATH`), with `VERTEX_PROJECT_ID` and `VERTEX_LOCATION`.
   - Discovers Vertex Gemini models (`gemini-2.5-flash`, `gemini-1.5-pro`, etc.) and registers `vertex` provider.
4. **Codex / ChatGPT Device Code Authentication**:
   - Device Authorization flow (`/api/ai/codex/device-code/` and `/api/ai/codex/poll/`) invoking OpenAI device auth.
   - Interactive Modal in Teklora Admin displaying the 15-minute one-time code (`Q1AY-Q4OY7`), link to `https://auth.openai.com/codex/device`, copy button, and live status polling.
   - Once authorized, automatically saves OAuth session tokens to database / config, activates the `codex` provider (`status='active'`, `enabled=True`), and displays subscription info.
5. **AI Configuration Admin Section & Model Catalogue Studio**:
   - Sidebar tab `AI Configuration` in `admin_base.html`.
   - Providers grid showing live `.env` and OAuth connection statuses (Connected 🟢 / Key Absent ⚪), latency/pricing metrics, and toggle switches.
   - Touchpoints Manager table showing name, key, description, assigned provider + model selector dropdown (filtered dynamically by model catalogue), and test invocation.
   - Model Catalogue Browser with search, pricing per 1M tokens, and capabilities tags.

---

## 2. Architecture & Data Model

### A. Touchpoint Registry Model
```python
class AITouchpoint(models.Model):
    key = models.CharField(max_length=80, unique=True) # e.g. 'assistant', 'writer', 'fact_verifier', 'project_summarizer'
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    default_role = models.CharField(max_length=40, default='analytic') # precise, analytic, creative, conversational
    
    # Administrative overrides:
    pinned_provider = models.CharField(max_length=40, blank=True, default='') # e.g. 'openai', 'gemini', 'vertex', 'codex'
    pinned_model = models.CharField(max_length=200, blank=True, default='')   # e.g. 'gpt-4o', 'gemini-2.5-flash'
    allow_fallback = models.BooleanField(default=True)
    temperature_override = models.FloatField(null=True, blank=True)
    
    last_invoked_at = models.DateTimeField(null=True, blank=True)
    total_invocations = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

### B. Python Registry Decorator Pattern
```python
from ai_workflows.harness.touchpoints import register_touchpoint

@register_touchpoint(
    key="writer",
    name="Editorial Article Writer",
    description="Drafts long-form authoritative tech news and analyses.",
    default_role="creative"
)
class WriterAgent(Agent):
    ...
```

---

## 3. Implementation Steps
1. Create `AITouchpoint` model in `ai_workflows/models.py` and run migration.
2. Build `ai_workflows/harness/touchpoints.py` with registry decorator, auto-discovery of touchpoints across Django installed apps, and resolution helper.
3. Update `ai_workflows/harness/llm.py` so `get_model` and `iter_models` accept `touchpoint="key"` and apply DB overrides.
4. Implement `VertexAIAdapter` in `ai_workflows/harness/providers.py` with `GOOGLE_APPLICATION_CREDENTIALS` json support and `_vertex` builder in `llm.py`.
5. Implement Codex Device Auth service and endpoints in `ai_workflows/views.py` and `ai_workflows/urls.py`.
6. Implement API endpoints for AI Configuration (`GET /api/ai/config/`, `POST /api/ai/touchpoints/<key>/`, `POST /api/ai/providers/<name>/toggle/`, `POST /api/ai/providers/refresh/`).
7. Create `_ai_config.html` admin partial and include in `admin_panel.html`, adding `nav-ai` sidebar item to `admin_base.html`.
8. Create `ai_config.js` static frontend module managing the providers cards, device auth modal, touchpoints table with provider/model dropdowns, and catalogue drawer.
9. Verify with test suite, update `CHANGELOG.md`, and run static asset compilation.
