import hashlib
import secrets
from django.conf import settings
from django.db import models

from .capabilities import permission_tuples


class StaffCapability(models.Model):
    """Owns the panel's permissions. Has no table and never holds rows.

    Django requires a permission to hang off a model. Attaching these to
    BlogPost, Campaign and friends would bury them among the auto-generated
    CRUD permissions, so they live here instead. managed = False means no
    table is created; default_permissions = () suppresses add/change/delete/
    view. post_migrate still creates the auth_permission rows, so these behave
    as ordinary Django permissions.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = permission_tuples()


class AuditEntry(models.Model):
    """Append-only record of role and account changes.

    There is no update or delete path in the API. `summary` is rendered when
    the entry is written so it still reads correctly after the user or group
    it names has been deleted.
    """

    ACTION_CHOICES = [
        ("invite_sent", "Invitation sent"),
        ("invite_resent", "Invitation resent"),
        ("invite_send_failed", "Invitation email failed"),
        ("invite_revoked", "Invitation revoked"),
        ("invite_accepted", "Invitation accepted"),
        ("roles_changed", "Groups changed"),
        ("user_deactivated", "Account deactivated"),
        ("user_reactivated", "Account reactivated"),
        ("group_created", "Group created"),
        ("group_updated", "Group updated"),
        ("group_deleted", "Group deleted"),
        ("handle_chosen", "Work address chosen"),
        ("onboarding_completed", "Onboarding completed"),
        ("mail_limit_changed", "Mail sending limit changed"),
        ("mailbox_created", "Shared mailbox created"),
        ("mailbox_deleted", "Shared mailbox deleted"),
        ("api_key_created", "Developer API key created"),
        ("api_key_revoked", "Developer API key revoked"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    target_group = models.ForeignKey(
        "auth.Group", on_delete=models.SET_NULL, null=True, blank=True
    )
    summary = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"
        default_permissions = ()

    def __str__(self):
        return self.summary


class StaffInvitation(models.Model):
    """A pending staff account. No User row exists until it is accepted."""

    email = models.EmailField()
    groups = models.ManyToManyField("auth.Group", blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    # When the invitation email last went out, which is not created_at once an
    # invitation has been resent. The seeding command needs this to tell a
    # still-valid invitation from one whose token has expired, so it can reissue
    # the dead one without mailing the live one again on every deployment.
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        default_permissions = ()
        constraints = [
            # Only PENDING invitations are unique. Accepted rows are kept as
            # history, and a plain unique=True on email would let one of them
            # block that address from ever being invited again - which is the
            # ordinary case of someone leaving and later being re-hired.
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(accepted_at__isnull=True),
                name="unique_pending_invitation_email",
            ),
        ]

    def __str__(self):
        return self.email


class StaffProfile(models.Model):
    """What a staff member keeps about themselves beyond auth.User.

    Created lazily by the /me endpoint rather than by a post_save signal, so
    accounts that predate this model need no backfill. `phone` is stored in
    E.164 (+254712345678) so it can be dropped straight into a wa.me link.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile"
    )
    phone = models.CharField(
        max_length=16, blank=True,
        help_text="E.164, e.g. +254712345678. A WhatsApp number is preferred.",
    )
    # Recipients per day this person may send to from any mailbox. Null
    # follows the company default in messaging.MailSettings; 0 suspends.
    daily_mail_limit = models.PositiveIntegerField(null=True, blank=True)

    # Where in the business they work (Marketing, Engineering, ...), picked
    # at onboarding and editable from the dashboard profile.
    scopes = models.JSONField(
        default=list, blank=True,
        help_text="Areas of the business, e.g. ['Marketing', 'Sales & Partnerships']",
    )

    # Technical capabilities and onboarding
    primary_role = models.CharField(
        max_length=64, blank=True, default="",
        help_text="e.g. Fullstack Engineer, Backend Developer, AI / ML Engineer, DevOps",
    )
    coding_languages = models.JSONField(
        default=list, blank=True,
        help_text="List of programming languages, e.g. ['Python', 'TypeScript']",
    )
    frameworks = models.JSONField(
        default=list, blank=True,
        help_text="List of frameworks & tools, e.g. ['Django', 'React', 'Docker']",
    )
    github_username = models.CharField(max_length=100, blank=True, default="")
    # Off keeps someone off work handed out automatically (roadmap items),
    # for instance while they are on another project. Manual assignment is
    # unaffected.
    auto_assign = models.BooleanField(default=True)
    bio = models.TextField(blank=True, default="")
    is_onboarded = models.BooleanField(
        default=False,
        help_text="True when the staff member has completed capabilities & WhatsApp onboarding.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()

    def __str__(self):
        return f"Profile of {self.user}"


class DeveloperApiKey(models.Model):
    """API key for developers and autonomous coding agents.

    Allows staff members to authenticate CLI tools, MCP servers, and AI
    agents directly against Teklora APIs without session cookies.
    The raw secret key is displayed only once upon generation; the database
    stores only a cryptographically secure SHA-256 hash and a prefix for
    identification in the UI.
    """

    KEY_PREFIX = "tkl_live_"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="developer_api_keys",
    )
    name = models.CharField(
        max_length=100,
        help_text="Name or device label, e.g. 'Claude Code' or 'Workstation Cursor'",
    )
    prefix = models.CharField(
        max_length=20,
        db_index=True,
        help_text="Visible prefix for key identification in UI, e.g. tkl_live_8f3a...",
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hash of the full secret token",
    )
    scopes = models.JSONField(
        default=list,
        blank=True,
        help_text="Permitted scopes, e.g. ['tasks', 'profile', 'knowledge_base']",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "developer API key"
        verbose_name_plural = "developer API keys"
        default_permissions = ()

    def __str__(self):
        return f"{self.name} ({self.prefix}) - {self.user.username}"

    @classmethod
    def hash_key(cls, raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    @classmethod
    def generate_key(cls, user, name: str = "", scopes: list = None, expires_at=None):
        """Generates a new secure API key and returns (instance, raw_key)."""
        raw_token = f"{cls.KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key_hash = cls.hash_key(raw_token)
        prefix = raw_token[:16] + "..."

        instance = cls.objects.create(
            user=user,
            name=name.strip() or f"Key {secrets.token_hex(3)}",
            prefix=prefix,
            key_hash=key_hash,
            scopes=scopes if scopes is not None else ["tasks", "profile", "knowledge_base"],
            expires_at=expires_at,
        )
        return instance, raw_token

    def revoke(self):
        self.is_active = False
        self.save(update_fields=["is_active"])

