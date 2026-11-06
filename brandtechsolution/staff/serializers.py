from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from rest_framework import serializers

from .capabilities import CODENAMES
from .models import AuditEntry, DeveloperApiKey, StaffInvitation
from .handles import mailbox_address, needs_handle
from .phone import normalize_phone
from .signups import TAKEN, account_for
from .profile_options import COMMON_FRAMEWORKS, COMMON_LANGUAGES, ROLE_CHOICES, SCOPE_CHOICES, clean_list


class RoleSerializer(serializers.ModelSerializer):
    # write_only=True keeps to_representation() from blowing up: Group has no
    # `capabilities` attribute of its own, so DRF's default get_attribute()
    # would raise AttributeError while rendering. A write-only field is
    # excluded from _readable_fields, so get_attribute() is never called on
    # read - to_representation() below always overwrites this field with the
    # computed value anyway, so the field is never missing from the response.
    # On write the field stays mandatory: a non-partial request (POST/PUT)
    # missing the key correctly fails validation with a 400, while PATCH
    # still skips it as partial-update semantics require.
    capabilities = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, write_only=True
    )
    member_count = serializers.IntegerField(read_only=True)
    # Shared mailbox names its members read and reply from. Optional on
    # write, so a client that predates groups-with-mailboxes keeps working.
    mailboxes = serializers.ListField(
        child=serializers.CharField(), allow_empty=True, write_only=True, required=False
    )
    # The whole membership, replacing it. RoleViewSet applies it, since each
    # added or removed person is a grant to check and audit on its own.
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True, write_only=True, required=False
    )

    class Meta:
        model = Group
        fields = ["id", "name", "capabilities", "member_count", "mailboxes", "member_ids"]

    def validate_mailboxes(self, value):
        from messaging.models import SharedMailbox

        names = sorted(set(value))
        known = set(SharedMailbox.objects.filter(name__in=names).values_list("name", flat=True))
        unknown = [n for n in names if n not in known]
        if unknown:
            raise serializers.ValidationError(f"Unknown mailboxes: {', '.join(unknown)}")
        return names

    def validate_member_ids(self, value):
        ids = sorted(set(value))
        found = set(User.objects.filter(pk__in=ids, is_staff=True).values_list("pk", flat=True))
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise serializers.ValidationError(
                f"Not staff accounts: {', '.join(missing)}. Invite them instead."
            )
        return ids

    def validate_capabilities(self, value):
        unknown = sorted(set(value) - set(CODENAMES))
        if unknown:
            raise serializers.ValidationError(
                f"Unknown capabilities: {', '.join(unknown)}"
            )
        return value

    def _apply(self, group, codenames):
        # Only this app's capabilities are replaced. A group can also carry
        # ordinary Django permissions - anything made through /admin/ before
        # this feature existed probably does - and the panel has no UI for
        # those, so a plain .set() would silently destroy them on any edit,
        # with the audit trail recording only the capability change.
        keep = list(group.permissions.exclude(content_type__app_label="staff"))
        group.permissions.set(
            list(
                Permission.objects.filter(
                    codename__in=codenames, content_type__app_label="staff"
                )
            )
            + keep
        )

    def _apply_mailboxes(self, group, names):
        from messaging.models import SharedMailbox

        group.shared_mailboxes.set(SharedMailbox.objects.filter(name__in=names))

    def create(self, validated_data):
        codenames = validated_data.pop("capabilities")
        mailboxes = validated_data.pop("mailboxes", [])
        validated_data.pop("member_ids", None)
        group = Group.objects.create(**validated_data)
        self._apply(group, codenames)
        self._apply_mailboxes(group, mailboxes)
        # Group.objects.create() bypasses the view's annotated queryset
        # (Count("user") -> member_count), so re-fetch through it to keep
        # the create response shape consistent with list/retrieve/update.
        return Group.objects.annotate(member_count=Count("user")).get(pk=group.pk)

    def update(self, instance, validated_data):
        codenames = validated_data.pop("capabilities", None)
        mailboxes = validated_data.pop("mailboxes", None)
        validated_data.pop("member_ids", None)
        instance.name = validated_data.get("name", instance.name)
        instance.save()
        if codenames is not None:
            self._apply(instance, codenames)
        if mailboxes is not None:
            self._apply_mailboxes(instance, mailboxes)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["capabilities"] = sorted(
            instance.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )
        data["mailboxes"] = sorted(m.name for m in instance.shared_mailboxes.all())
        members = sorted(instance.user_set.all(), key=lambda u: (u.get_full_name() or u.username).lower())
        data["members"] = [
            {
                "id": u.id,
                "name": u.get_full_name() or u.username,
                "username": u.username,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
            }
            for u in members
        ]
        data["invited"] = sorted(
            i.email for i in instance.staffinvitation_set.all() if i.accepted_at is None
        )
        return data


class PersonSerializer(serializers.ModelSerializer):
    # `roles` is read-only and computed by get_roles(); `role_ids` is the
    # write path (source="groups") and is write_only=True so DRF's default
    # get_attribute() never looks for a `role_ids` attribute on the User
    # instance when rendering a response - that attribute doesn't exist and
    # would raise AttributeError on read otherwise.
    roles = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    primary_role = serializers.SerializerMethodField()
    scopes = serializers.SerializerMethodField()
    coding_languages = serializers.SerializerMethodField()
    frameworks = serializers.SerializerMethodField()
    github_username = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    is_onboarded = serializers.SerializerMethodField()
    role_ids = serializers.PrimaryKeyRelatedField(
        source="groups", queryset=Group.objects.all(), many=True, write_only=True,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "is_active", "is_staff", "is_superuser", "roles", "role_ids", "date_joined",
            "last_login", "phone", "primary_role", "scopes", "coding_languages",
            "frameworks", "github_username", "bio", "is_onboarded",
        ]
        read_only_fields = [
            "username", "is_staff", "is_superuser", "date_joined", "last_login",
        ]

    def get_roles(self, obj):
        return sorted(g.name for g in obj.groups.all())

    def get_phone(self, obj):
        # Set by its owner through /me. Accounts that never opened their
        # profile have no row yet.
        profile = getattr(obj, "staff_profile", None)
        return profile.phone if profile else ""

    def get_primary_role(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.primary_role if profile else ""

    def get_scopes(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.scopes if profile else []

    def get_coding_languages(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.coding_languages if profile else []

    def get_frameworks(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.frameworks if profile else []

    def get_github_username(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.github_username if profile else ""

    def get_bio(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.bio if profile else ""

    def get_is_onboarded(self, obj):
        profile = getattr(obj, "staff_profile", None)
        return profile.is_onboarded if profile else False


class AuditEntrySerializer(serializers.ModelSerializer):
    # A SerializerMethodField rather than CharField(source="actor.username",
    # default=...): DRF asserts you may not set both read_only and default,
    # and `actor` is SET_NULL, so the None case has to be handled explicitly.
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditEntry
        fields = ["id", "action", "summary", "actor_name", "created_at"]

    def get_actor_name(self, obj):
        return obj.actor.username if obj.actor else "system"


class InvitationSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    role_ids = serializers.PrimaryKeyRelatedField(
        source="groups", queryset=Group.objects.all(), many=True, write_only=True,
        required=False,
    )

    class Meta:
        model = StaffInvitation
        fields = ["id", "email", "roles", "role_ids", "created_at", "accepted_at"]
        read_only_fields = ["created_at", "accepted_at"]

    def get_roles(self, obj):
        return sorted(g.name for g in obj.groups.all())

    def validate_email(self, value):
        email = value.strip().lower()
        # A lone /signup/ account is fine: accepting takes it over.
        if account_for(email) is TAKEN:
            raise serializers.ValidationError(
                "A staff account with this email already exists. "
                "Edit that person's roles instead."
            )
        return email


class MeSerializer(serializers.ModelSerializer):
    """The signed-in user's own profile. Email and username are read-only:
    the username is the handle picked once at /staff/address/, and both are
    how they sign in, so changing either belongs to whoever manages staff."""

    phone = serializers.CharField(
        source="staff_profile.phone", required=False, allow_blank=True, max_length=32
    )
    primary_role = serializers.CharField(
        source="staff_profile.primary_role", required=False, allow_blank=True, max_length=64
    )
    scopes = serializers.ListField(
        child=serializers.CharField(max_length=64, allow_blank=True),
        source="staff_profile.scopes",
        required=False,
        allow_empty=True,
        max_length=30,
    )
    coding_languages = serializers.ListField(
        child=serializers.CharField(),
        source="staff_profile.coding_languages",
        required=False,
        allow_empty=True,
    )
    frameworks = serializers.ListField(
        child=serializers.CharField(),
        source="staff_profile.frameworks",
        required=False,
        allow_empty=True,
    )
    github_username = serializers.CharField(
        source="staff_profile.github_username", required=False, allow_blank=True, max_length=100
    )
    bio = serializers.CharField(
        source="staff_profile.bio", required=False, allow_blank=True
    )
    is_onboarded = serializers.BooleanField(
        source="staff_profile.is_onboarded", required=False
    )
    mailbox = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "mailbox", "first_name", "last_name",
            "phone", "primary_role", "scopes", "coding_languages", "frameworks",
            "github_username", "bio", "is_onboarded", "options",
        ]
        read_only_fields = ["id", "username", "email"]

    def get_mailbox(self, obj):
        return None if needs_handle(obj) else mailbox_address(obj.username)

    def get_options(self, obj):
        # The suggestions onboarding offers, so the dashboard editor offers
        # the same ones. They are only suggestions: values may be anything.
        return {
            "scopes": SCOPE_CHOICES,
            "roles": ROLE_CHOICES,
            "languages": COMMON_LANGUAGES,
            "frameworks": COMMON_FRAMEWORKS,
        }

    def validate_scopes(self, value):
        return clean_list(value)

    def validate_phone(self, value):
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("staff_profile", None)
        instance = super().update(instance, validated_data)
        if profile_data is not None:
            profile = instance.staff_profile
            for field in (
                "phone",
                "primary_role",
                "scopes",
                "coding_languages",
                "frameworks",
                "github_username",
                "bio",
                "is_onboarded",
            ):
                if field in profile_data:
                    setattr(profile, field, profile_data[field])
            profile.save()
        return instance


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("That is not your current password.")
        return value

    def validate_new_password(self, value):
        try:
            validate_password(value, user=self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value


class DeveloperApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = DeveloperApiKey
        fields = [
            "id",
            "name",
            "prefix",
            "scopes",
            "is_active",
            "created_at",
            "last_used_at",
            "expires_at",
        ]
        read_only_fields = [
            "id",
            "prefix",
            "is_active",
            "created_at",
            "last_used_at",
            "expires_at",
        ]

