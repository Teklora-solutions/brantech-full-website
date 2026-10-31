from django.urls import path
from . import views

app_name = 'ai_workflows'

urlpatterns = [
    path('chat/', views.chat_endpoint, name='chat'),
    path('chat/history/', views.chat_history, name='chat_history'),
    path('chat/clear/', views.clear_chat_history, name='clear_chat_history'),

    # AI Configuration, Touchpoints & Codex Auth endpoints
    path('config/', views.ai_config_summary, name='ai_config_summary'),
    path('touchpoints/<str:key>/', views.update_touchpoint_config, name='update_touchpoint_config'),
    path('providers/<str:name>/toggle/', views.toggle_provider, name='toggle_provider'),
    path('providers/refresh/', views.refresh_provider_catalogue, name='refresh_provider_catalogue'),
    path('codex/device-auth/', views.codex_start_device_auth, name='codex_start_device_auth'),
    path('codex/poll/', views.codex_poll_device_auth, name='codex_poll_device_auth'),
]


