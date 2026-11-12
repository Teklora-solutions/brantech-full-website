from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, re_path
from brand import views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve

urlpatterns = [
    # Django admin's own login form has none of /login/'s bot throttling
    # (brand/login_throttle.py), so it signs in through the same view.
    path('admin/login/', views.login_view),
    path('admin/', admin.site.urls),
    path('', include('brand.urls')),
    path('', include('messaging.urls')),
    path('appointments/', include('appointments.urls')),
    path('api/', include('brand.api_urls')),
    path('api/ai/', include('ai_workflows.urls')),
    path('api/messaging/', include('messaging.api_urls')),

    path('api/staff/', include('staff.api_urls')),
    path('api/work/', include('tasks.api_urls')),
    path('staff/', include('staff.urls')),

    path('editorial/', include('editorial.urls')),
    path('library/', include('knowledge_base.urls')),

    path('research/', views.research, name='research'),
    path('accounts/login/', views.login_view),
    path('accounts/logout/', views.logout_view),
    # The site's own reset pages. They have to be named explicitly: admin is
    # listed before brand in INSTALLED_APPS, so a bare registration/...
    # template name resolves to Django admin's plain version.
    path('accounts/password_reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='brand/auth/password_reset_done.html'), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='brand/auth/password_reset_confirm.html'), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='brand/auth/password_reset_complete.html'), name='password_reset_complete'),
    path('accounts/', include('django.contrib.auth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production (DEBUG=False) WhiteNoise serves static but not user media,
    # so serve uploaded media files through Django.
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$',
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
