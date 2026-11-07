from django.contrib import admin
from .models import AuditEntry, DeveloperApiKey, StaffInvitation, StaffProfile


@admin.register(DeveloperApiKey)
class DeveloperApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "prefix", "is_active", "created_at", "last_used_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "user__username", "user__email", "prefix")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "primary_role", "phone", "github_username", "is_onboarded")
    search_fields = ("user__username", "user__email", "phone", "github_username")


@admin.register(StaffInvitation)
class StaffInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "invited_by", "created_at", "accepted_at")
    search_fields = ("email",)


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "target_user", "created_at", "summary")
    list_filter = ("action", "created_at")
    search_fields = ("summary", "actor__username", "target_user__username")
    readonly_fields = ("created_at",)
