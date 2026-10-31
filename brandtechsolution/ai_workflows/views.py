from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from brandtechsolution.ratelimit import rate_limited
from .service import get_chatbot_response, ChatAssistant
from .models import ConversationThread, ConversationCheckpoint
import uuid
import json
import traceback
import logging

logger = logging.getLogger(__name__)


def _own_thread_id(request, requested, create):
    """The conversation this visitor may read and write, never one they name.

    A thread id sent by the browser is only a hint. It is honoured when the
    thread already belongs to the signed-in user; any other id (someone else's,
    unknown, or sent while signed out) is ignored, so knowing or guessing an id
    gives no access to that conversation. Signed-out visitors always get the
    thread stored in their own session.
    """
    user = request.user
    if not user.is_authenticated:
        if 'chat_thread_id' not in request.session:
            request.session['chat_thread_id'] = f"anon_{uuid.uuid4().hex[:12]}"
        return request.session['chat_thread_id']

    mine = ConversationThread.objects.filter(user=user, workflow_type='chatbot')
    thread = None
    if requested:
        thread = mine.filter(thread_id=requested).first()
    if thread is None:
        thread = mine.order_by('-updated_at').first()
    if thread is not None:
        return thread.thread_id

    thread_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    if create:
        ConversationThread.objects.create(
            thread_id=thread_id, user=user, workflow_type='chatbot',
        )
    return thread_id


@ensure_csrf_cookie
@require_http_methods(["POST"])
def chat_endpoint(request):
    """Chatbot endpoint using Django sessions"""

    # Every message is a paid model call that holds a web worker for seconds,
    # on a public endpoint. Unlimited, a script would spend the model quota
    # and queue every other visitor's page load behind its own requests.
    if rate_limited(
        request, 'chat',
        limit=settings.CHAT_RATE_LIMIT_COUNT,
        window_seconds=settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
    ):
        return JsonResponse(
            {"error": "You are sending messages too quickly. Please wait a few minutes."},
            status=429,
        )

    try:
        data = json.loads(request.body)
        message = data.get('message')
        
        logger.info(f"[chat_endpoint] Received message request")
        logger.debug(f"[chat_endpoint] Message: {message[:100] if message else 'None'}...")
        
        if not message:
            logger.warning("[chat_endpoint] No message provided")
            return JsonResponse(
                {"error": "Message is required"},
                status=400
            )
        
        user = request.user
        is_authenticated = user.is_authenticated
        logger.debug(f"[chat_endpoint] User authenticated: {is_authenticated}, user_id: {user.id if is_authenticated else 'None'}")
        
        thread_id = _own_thread_id(request, data.get('thread_id'), create=True)
        
        logger.info(f"[chat_endpoint] Using thread_id={thread_id}")
        
        # Get chatbot response
        result = get_chatbot_response(
            message=message,
            thread_id=thread_id,
            user_id=user.id if is_authenticated else None,
        )
        
        logger.info(f"[chat_endpoint] Response generated successfully")
        
        # Store in session for anonymous users (for history)
        if not is_authenticated:
            if 'chat_messages' not in request.session:
                request.session['chat_messages'] = []
            request.session['chat_messages'].append({
                'role': 'user',
                'content': message,
            })
            request.session['chat_messages'].append({
                'role': 'assistant',
                'content': result['response'],
            })
            # Keep only last 10 messages in session to reduce session size
            # (5 exchanges = 10 messages)
            if len(request.session['chat_messages']) > 10:
                request.session['chat_messages'] = request.session['chat_messages'][-10:]
            request.session.modified = True
        
        return JsonResponse({
            "response": result['response'],
            "thread_id": thread_id,
            # Additive since step 7. The prompt has always asked the model for
            # these and nothing parsed them, so they went out as part of the
            # visible reply text; now they are separated and the caller can use
            # them or ignore them.
            "sources": result['metadata'].get('sources', []),
            "suggested_questions": result['metadata'].get('suggested_questions', []),
        })
        
    except Exception as e:
        # Log the full traceback for debugging
        error_traceback = traceback.format_exc()
        logger.error(f"[chat_endpoint] Error: {str(e)}\n{error_traceback}")
        
        # The message stays in the log: provider errors can carry request
        # details, and this endpoint answers anyone.
        return JsonResponse(
            {
                "error": "The assistant could not answer just now. Please try again.",
                "traceback": error_traceback if settings.DEBUG else None
            },
            status=500
        )


@ensure_csrf_cookie
@require_http_methods(["GET"])
def chat_history(request):
    """Get conversation history"""
    
    logger.info(f"[chat_history] Getting conversation history")
    
    user = request.user
    is_authenticated = user.is_authenticated
    thread_id = _own_thread_id(request, request.GET.get('thread_id'), create=False)

    logger.info(f"[chat_history] Using thread_id={thread_id}")
    
    # Use ChatAssistant to retrieve history consistently
    assistant = ChatAssistant(
        thread_id=thread_id,
        user_id=user.id if is_authenticated else None
    )
    history = assistant.get_history()
    
    logger.info(f"[chat_history] Returning {len(history)} messages")
    
    return JsonResponse({
        "thread_id": thread_id,
        "messages": history,
    })
    
    # if is_authenticated:
    #     # Get from database
    #     thread_id = request.GET.get('thread_id')
    #     if not thread_id:
    #         # Get user's most recent thread
    #         thread = ConversationThread.objects.filter(
    #             user=user,
    #             workflow_type='chatbot'
    #         ).order_by('-updated_at').first()
            
    #         if not thread:
    #             # Create a new thread for the user
    #             thread = ConversationThread.objects.create(
    #                 user=user,
    #                 workflow_type='chatbot',
    #                 thread_id=f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    #             )
    #         thread_id = thread.thread_id
        
    #     try:
    #         thread = ConversationThread.objects.get(
    #             thread_id=thread_id,
    #             user=user
    #         )
            
    #         checkpoints = ConversationCheckpoint.objects.filter(
    #             thread=thread
    #         ).order_by('created_at')
            
    #         messages = []
    #         for checkpoint in checkpoints:
    #             state = checkpoint.state
    #             if "messages" in state:
    #                 for msg in state["messages"]:
    #                     if isinstance(msg, dict):
    #                         role = msg.get("role", msg.get("type", "unknown"))
    #                         content = msg.get("content", msg.get("text", ""))
    #                         if isinstance(content, list):
    #                             text_parts = []
    #                             for part in content:
    #                                 if isinstance(part, dict) and "text" in part:
    #                                     text_parts.append(part["text"])
    #                                 elif isinstance(part, str):
    #                                     text_parts.append(part)
    #                             content = "\n".join(text_parts) if text_parts else str(content)
                            
    #                         if role in ['user', 'assistant', 'human', 'ai']:
    #                             messages.append({
    #                                 "role": "user" if role in ['user', 'human'] else "assistant",
    #                                 "content": content,
    #                                 "timestamp": checkpoint.created_at.isoformat(),
    #                             })
            
    #         return JsonResponse({
    #             "thread_id": thread_id,
    #             "messages": messages,
    #         })
            
    #     except ConversationThread.DoesNotExist:
    #         return JsonResponse({
    #             "thread_id": thread_id,
    #             "messages": []
    #         })
    # else:
    #     # Get from session - create if doesn't exist
    #     if 'chat_thread_id' not in request.session:
    #         request.session['chat_thread_id'] = f"anon_{uuid.uuid4().hex[:12]}"
    #         request.session.modified = True
    #     thread_id = request.session['chat_thread_id']
    #     messages = request.session.get('chat_messages', [])
        
    #     return JsonResponse({
    #         "thread_id": thread_id,
    #         "messages": messages,
    #     })


@ensure_csrf_cookie
@require_http_methods(["POST"])
def clear_chat_history(request):
    """Clear conversation history"""
    
    user = request.user
    is_authenticated = user.is_authenticated
    
    if is_authenticated:
        thread_id = json.loads(request.body).get('thread_id')
        if thread_id:
            try:
                thread = ConversationThread.objects.get(
                    thread_id=thread_id,
                    user=user
                )
                thread.delete()
                return JsonResponse({"success": True})
            except ConversationThread.DoesNotExist:
                return JsonResponse({"error": "Thread not found"}, status=404)
        else:
            # Delete all user's threads
            ConversationThread.objects.filter(
                user=user,
                workflow_type='chatbot'
            ).delete()
            return JsonResponse({"success": True})
    else:
        # Clear session
        if 'chat_thread_id' in request.session:
            del request.session['chat_thread_id']
        if 'chat_messages' in request.session:
            del request.session['chat_messages']
        request.session.modified = True
        return JsonResponse({"success": True})


# ============================================================
# AI CONFIGURATION, TOUCHPOINTS & CODEX ADMIN ENDPOINTS
# ============================================================


@staff_member_required
@require_http_methods(["GET"])
def ai_config_summary(request):
    """Return live status of all LLM providers, touchpoints, and model catalogue."""
    from ai_workflows.models import Provider, CatalogueEntry, AITouchpoint
    from ai_workflows.harness.providers import ADAPTERS
    from ai_workflows.harness.touchpoints import sync_registered_touchpoints
    from ai_workflows.harness.codex_auth import CodexDeviceAuthService

    # 1. Sync in-memory touchpoints into DB
    sync_registered_touchpoints()

    # 2. Providers status
    db_providers = {p.name: p for p in Provider.objects.all()}
    providers_data = []

    for name, adapter in sorted(ADAPTERS.items(), key=lambda x: x[1].preference):
        db_p = db_providers.get(name)
        has_cred = adapter.has_credential()
        enabled = db_p.enabled if db_p else adapter.default_enabled
        default_model = db_p.default_model if db_p else ""
        if not default_model and name == "gemini":
            default_model = getattr(config, "gemini_chat_model", "gemini-2.5-flash")

        # Models count
        model_count = CatalogueEntry.objects.filter(provider=name, available=True).count()
        if model_count == 0:
            # Fall back to adapter's statically declared models if not refreshed yet
            try:
                model_count = len(adapter.list_models())
            except Exception:
                model_count = 0

        providers_data.append({
            "name": name,
            "billing": adapter.billing,
            "preference": db_p.preference if db_p else adapter.preference,
            "has_credential": has_cred,
            "enabled": enabled,
            "status": "active" if has_cred and enabled else ("candidate" if has_cred else "absent"),
            "default_model": default_model,
            "model_count": model_count,
            "last_checked_at": db_p.last_checked_at.isoformat() if db_p and db_p.last_checked_at else None,
            "last_error": db_p.last_error if db_p else "",
        })

    # 3. Touchpoints
    touchpoints = []
    for tp in AITouchpoint.objects.all():
        touchpoints.append({
            "key": tp.key,
            "name": tp.name,
            "description": tp.description,
            "default_role": tp.default_role,
            "pinned_provider": tp.pinned_provider,
            "pinned_model": tp.pinned_model,
            "allow_fallback": tp.allow_fallback,
            "temperature_override": tp.temperature_override,
            "total_invocations": tp.total_invocations,
            "last_invoked_at": tp.last_invoked_at.isoformat() if tp.last_invoked_at else None,
            "is_active": tp.is_active,
        })

    # 4. Available models catalogue mapped by provider
    models_by_provider = {}
    for entry in CatalogueEntry.objects.filter(available=True).order_by("provider", "model_id"):
        models_by_provider.setdefault(entry.provider, []).append({
            "model_id": entry.model_id,
            "display_name": entry.display_name or entry.model_id,
            "context_tokens": entry.context_tokens,
            "input_price": float(entry.input_price_per_mtok) if entry.input_price_per_mtok is not None else None,
            "output_price": float(entry.output_price_per_mtok) if entry.output_price_per_mtok is not None else None,
        })

    # If any adapter has models not yet in CatalogueEntry, add them
    for name, adapter in ADAPTERS.items():
        if name not in models_by_provider or not models_by_provider[name]:
            try:
                for m in adapter.list_models():
                    models_by_provider.setdefault(name, []).append({
                        "model_id": m.model_id,
                        "display_name": m.display_name or m.model_id,
                        "context_tokens": m.context_tokens,
                        "input_price": m.input_price_per_mtok,
                        "output_price": m.output_price_per_mtok,
                    })
            except Exception:
                pass

    codex_status = CodexDeviceAuthService.get_status()

    return JsonResponse({
        "success": True,
        "providers": providers_data,
        "touchpoints": touchpoints,
        "models_by_provider": models_by_provider,
        "codex": codex_status,
    })


@staff_member_required
@require_http_methods(["POST"])
def update_touchpoint_config(request, key):
    """Update administrative LLM routing for a specific touchpoint."""
    from ai_workflows.models import AITouchpoint

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    tp, _ = AITouchpoint.objects.get_or_create(key=key, defaults={"name": key.title()})

    if "pinned_provider" in data:
        tp.pinned_provider = (data["pinned_provider"] or "").strip()
    if "pinned_model" in data:
        tp.pinned_model = (data["pinned_model"] or "").strip()
    if "allow_fallback" in data:
        tp.allow_fallback = bool(data["allow_fallback"])
    if "temperature_override" in data:
        val = data["temperature_override"]
        tp.temperature_override = float(val) if val is not None and str(val).strip() != "" else None
    if "is_active" in data:
        tp.is_active = bool(data["is_active"])

    tp.save()

    return JsonResponse({
        "success": True,
        "touchpoint": {
            "key": tp.key,
            "name": tp.name,
            "pinned_provider": tp.pinned_provider,
            "pinned_model": tp.pinned_model,
            "allow_fallback": tp.allow_fallback,
            "temperature_override": tp.temperature_override,
            "is_active": tp.is_active,
        }
    })


@staff_member_required
@require_http_methods(["POST"])
def toggle_provider(request, name):
    """Toggle a provider's active/enabled state or set its default model."""
    from ai_workflows.models import Provider
    from ai_workflows.harness.providers import get_adapter

    try:
        adapter = get_adapter(name)
    except KeyError:
        return JsonResponse({"error": f"Unknown provider {name}"}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    row, _ = Provider.objects.get_or_create(
        name=name,
        defaults={
            "billing": adapter.billing,
            "preference": adapter.preference,
            "enabled": adapter.default_enabled,
        }
    )

    if "enabled" in data:
        row.enabled = bool(data["enabled"])
    if "default_model" in data:
        row.default_model = (data["default_model"] or "").strip()
    if "preference" in data:
        row.preference = int(data["preference"])

    row.save()

    return JsonResponse({
        "success": True,
        "provider": {
            "name": row.name,
            "enabled": row.enabled,
            "default_model": row.default_model,
            "preference": row.preference,
        }
    })


@staff_member_required
@require_http_methods(["POST"])
def codex_start_device_auth(request):
    """Initiate ChatGPT Codex device code authorization."""
    from ai_workflows.harness.codex_auth import CodexDeviceAuthService

    res = CodexDeviceAuthService.start_device_auth()
    return JsonResponse(res)


@staff_member_required
@require_http_methods(["GET"])
def codex_poll_device_auth(request):
    """Poll in-flight device auth status."""
    from ai_workflows.harness.codex_auth import CodexDeviceAuthService

    session_id = request.GET.get("session_id", "")
    if not session_id:
        return JsonResponse({"error": "session_id required"}, status=400)

    res = CodexDeviceAuthService.poll_session(session_id)
    return JsonResponse(res)


@staff_member_required
@require_http_methods(["POST"])
def refresh_provider_catalogue(request):
    """Trigger a refresh of the model catalogue across providers."""
    from ai_workflows.harness.catalogue import refresh_all

    try:
        summary = refresh_all()
        return JsonResponse({"success": True, "summary": summary})
    except Exception as e:
        logger.exception("[catalogue] Refresh failed: %s", e)
        return JsonResponse({"error": str(e)}, status=500)

