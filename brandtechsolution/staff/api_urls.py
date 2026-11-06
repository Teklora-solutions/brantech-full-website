from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api

router = DefaultRouter()
router.register(r"roles", api.RoleViewSet, basename="roles")
router.register(r"people", api.PersonViewSet, basename="people")
router.register(r"invitations", api.InvitationViewSet, basename="invitations")
router.register(r"activity", api.AuditViewSet, basename="activity")

urlpatterns = [
    path("", include(router.urls)),
    path("capabilities/", api.capabilities, name="capabilities"),
    path("me/", api.me, name="me"),
    path("me/password/", api.change_password, name="me-password"),
    path("developer/keys/", api.developer_keys, name="developer-keys"),
    path("developer/keys/<int:pk>/revoke/", api.revoke_developer_key, name="developer-key-revoke"),
]
