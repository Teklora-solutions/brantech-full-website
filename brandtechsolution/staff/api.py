from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from brandtechsolution.ratelimit import rate_limited

from .audit import record
from .capabilities import CAPABILITY_GROUPS
from .emails import send_invitation
from .models import AuditEntry, StaffInvitation, StaffProfile
from .permissions import enforce_grantable_roles, has_capability
from .signups import TAKEN as ACCOUNT_TAKEN, account_for
from .serializers import (
    AuditEntrySerializer,
    InvitationSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    PersonSerializer,
    RoleSerializer,
)


class StaffPagination(PageNumberPagination):
    page_size = 50


@api_view(["GET"])
@permission_classes([has_capability("manage_staff")])
def capabilities(request):
    """The capability registry, grouped as the UI displays it."""
    return Response([
        {
            "label": label,
            "capabilities": [
                {"codename": codename, "label": text} for codename, text in pairs
            ],
        }
        for label, pairs in CAPABILITY_GROUPS
    ])


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return Group.objects.annotate(member_count=Count("user")).prefetch_related(
            "user_set", "shared_mailboxes", "staffinvitation_set"
        ).order_by("name")

    def _mailboxes(self, group):
        return sorted(group.shared_mailboxes.values_list("name", flat=True))

    def _snapshot(self, group):
        return {"capabilities": self._codenames(group), "mailboxes": self._mailboxes(group)}

    def _codenames(self, group):
        return sorted(
            group.permissions.filter(
                content_type__app_label="staff"
            ).values_list("codename", flat=True)
        )

    def _enforce_grantable_capabilities(self, serializer):
        """Refuse to ADD a capability the actor does not hold themselves.

        enforce_grantable_roles guards granting a role to a person, but
        editing a role reaches the same place by another door: a manage_staff
        holder who belongs to a role can otherwise tick every capability into
        that role and reload, granting themselves the whole registry. Only
        additions are checked - removing a capability is de-escalation.
        """
        actor = self.request.user
        if actor.is_superuser:
            return
        before = set(self._codenames(serializer.instance)) if serializer.instance else set()
        after = set(serializer.validated_data.get("capabilities", []))
        for codename in sorted(after - before):
            if not actor.has_perm(f"staff.{codename}"):
                raise PermissionDenied(
                    f"You cannot add the '{codename}' capability to a group: "
                    "you do not hold it yourself."
                )

        # The same rule for mailboxes: adding one hands its mail to every
        # member, so the actor must be able to send from it themselves.
        if "mailboxes" not in serializer.validated_data:
            return
        from messaging.mailbox import can_send_shared

        before = set(self._mailboxes(serializer.instance)) if serializer.instance else set()
        for name in sorted(set(serializer.validated_data["mailboxes"]) - before):
            if not can_send_shared(actor, name):
                raise PermissionDenied(
                    f"You cannot add the shared mailbox '{name}' to a group: "
                    "you cannot send from it yourself."
                )

    def _apply_members(self, group, member_ids):
        """Replace the group's membership, one checked and audited change per
        person. Runs inside the caller's transaction, after the group itself
        is saved, so additions are checked against what it now grants."""
        if member_ids is None:
            return
        actor = self.request.user
        current = {u.pk: u for u in group.user_set.all()}
        wanted = set(member_ids)
        added = User.objects.filter(pk__in=wanted - set(current)).prefetch_related("groups")
        removed = [u for pk, u in current.items() if pk not in wanted]
        changed = list(added) + removed

        # The person editor's rules, so the group editor is not a way round them.
        for person in changed:
            if person.pk == actor.pk and not actor.is_superuser:
                raise PermissionDenied("You cannot change your own groups.")
            if person.is_superuser and not actor.is_superuser:
                raise PermissionDenied("You cannot change a superuser's groups.")
        if added:
            enforce_grantable_roles(actor, [group])

        for person in changed:
            before = sorted(g.name for g in person.groups.all())
            if person.pk in current:
                person.groups.remove(group)
            else:
                person.groups.add(group)
            after = sorted(g.name for g in person.groups.all())
            record(
                actor=actor,
                action="roles_changed",
                summary=f"{actor} changed {person}'s groups to {', '.join(after) or 'none'}",
                target_user=person,
                target_group=group,
                detail={"before": before, "after": after},
            )

    def _fresh(self, group):
        return self.get_queryset().get(pk=group.pk)

    def perform_create(self, serializer):
        member_ids = serializer.validated_data.get("member_ids")
        with transaction.atomic():
            self._enforce_grantable_capabilities(serializer)
            group = serializer.save()
            record(
                actor=self.request.user,
                action="group_created",
                summary=f"{self.request.user} created the group {group.name}",
                target_group=group,
                detail={"after": self._snapshot(group)},
            )
            self._apply_members(group, member_ids)
        serializer.instance = self._fresh(group)

    def perform_update(self, serializer):
        member_ids = serializer.validated_data.get("member_ids")
        with transaction.atomic():
            self._enforce_grantable_capabilities(serializer)
            before = self._snapshot(serializer.instance)
            group = serializer.save()
            after = self._snapshot(group)
            if after != before or group.name != serializer.instance.name:
                record(
                    actor=self.request.user,
                    action="group_updated",
                    summary=f"{self.request.user} changed the group {group.name}",
                    target_group=group,
                    detail={"before": before, "after": after},
                )
            self._apply_members(group, member_ids)
        serializer.instance = self._fresh(group)

    def perform_destroy(self, instance):
        with transaction.atomic():
            name = instance.name
            record(
                actor=self.request.user,
                action="group_deleted",
                summary=f"{self.request.user} deleted the group {name}",
                detail={"before": self._snapshot(instance), "name": name},
            )
            instance.delete()


class PersonViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Staff accounts. Creation happens through invitations, not here.

    ?include=signups adds accounts made through the public /signup/ form to
    the list, so the roster can find them. They are list-only: nothing here
    can edit one, since the sign-up never proved its address. An invitation
    to that address is how one becomes staff (see staff/signups.py).
    """

    serializer_class = PersonSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        queryset = User.objects.select_related(
            "staff_profile"
        ).prefetch_related("groups").order_by(
            "username"
        )
        if self.action == "list" and self.request.query_params.get("include") == "signups":
            return queryset
        return queryset.filter(is_staff=True)

    def perform_update(self, serializer):
        actor = self.request.user
        target = serializer.instance

        # A non-superuser editing themselves could drop manage_staff or switch
        # off their own account and lock the panel. One flat rule beats
        # last-admin-standing arithmetic; superusers remain the escape hatch.
        if target.pk == actor.pk and not actor.is_superuser:
            raise PermissionDenied(
                "You cannot change your own roles or deactivate your own account."
            )

        # The site currently has exactly one superuser: the owner. Without
        # this check, anyone delegated manage_staff could reassign the
        # owner's roles or deactivate their account and lock them out of
        # their own site. Superusers remain the escape hatch and can manage
        # each other (including themselves) freely.
        if target.is_superuser and not actor.is_superuser:
            raise PermissionDenied(
                "You cannot change a superuser's roles or active state."
            )

        # An actor may only grant capabilities they already hold. Only
        # additions are checked - removing a role is de-escalation and stays
        # unrestricted, so an admin can still clean up an account even if
        # they don't personally hold every capability being stripped.
        if "groups" in serializer.validated_data:
            current_roles = set(target.groups.all())
            new_roles = set(serializer.validated_data["groups"])
            enforce_grantable_roles(actor, new_roles - current_roles)

        with transaction.atomic():
            before_roles = sorted(g.name for g in target.groups.all())
            was_active = target.is_active
            person = serializer.save()
            after_roles = sorted(g.name for g in person.groups.all())

            if after_roles != before_roles:
                record(
                    actor=actor,
                    action="roles_changed",
                    summary=(
                        f"{actor} changed {person}'s roles to "
                        f"{', '.join(after_roles) or 'none'}"
                    ),
                    target_user=person,
                    detail={"before": before_roles, "after": after_roles},
                )

            if person.is_active != was_active:
                action = "user_reactivated" if person.is_active else "user_deactivated"
                verb = "reactivated" if person.is_active else "deactivated"
                record(
                    actor=actor,
                    action=action,
                    summary=f"{actor} {verb} {person}",
                    target_user=person,
                )


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The activity feed. Read-only by construction: no create, update or
    destroy route is mixed in, matching AuditEntry's append-only contract."""

    serializer_class = AuditEntrySerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination
    queryset = AuditEntry.objects.select_related(
        "actor", "target_user", "target_group"
    )


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = InvitationSerializer
    permission_classes = [has_capability("manage_staff")]
    pagination_class = StaffPagination

    def get_queryset(self):
        return StaffInvitation.objects.filter(
            accepted_at__isnull=True
        ).prefetch_related("groups")

    def perform_create(self, serializer):
        # Inviting someone with roles is a grant, made before any account
        # exists: without this check a manage_staff holder could invite a
        # second address of their own carrying the Administrator role and
        # accept that invitation themselves, trivially escalating past the
        # same restriction PersonViewSet.perform_update enforces on existing
        # accounts. Checked before serializer.save() so a forbidden request
        # never creates the invitation row.
        roles = serializer.validated_data.get("groups", [])
        enforce_grantable_roles(self.request.user, roles)

        with transaction.atomic():
            invitation = serializer.save(invited_by=self.request.user)
            record(
                actor=self.request.user,
                action="invite_sent",
                summary=f"{self.request.user} invited {invitation.email}",
                detail={"email": invitation.email,
                        "roles": sorted(g.name for g in invitation.groups.all())},
            )
        # Deliberately outside the transaction, and deliberately NOT rolling
        # it back on failure: if the mail server is down we keep the
        # invitation row so it can be resent, rather than losing it. The
        # trade-off is that the audit entry can outlive a send that failed,
        # so the failure is recorded too instead of surfacing as a 500.
        try:
            send_invitation(invitation, self.request)
        except Exception:
            record(
                actor=self.request.user,
                action="invite_send_failed",
                summary=(
                    f"Invitation email to {invitation.email} could not be sent"
                ),
                detail={"email": invitation.email},
            )

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        """Send a fresh link for an invitation that is still pending.

        No model change is needed: tokens are signed with a timestamp at
        generation, so a newly minted token carries a full 7-day window on
        its own. get_queryset() already excludes accepted invitations, so an
        accepted one 404s here rather than re-opening a closed account.
        """
        invitation = self.get_object()

        # The address may have been registered through the public /signup/
        # page since the invitation was issued, in which case accepting it
        # cannot succeed - so resending would only mail a link that dead-ends.
        if account_for(invitation.email) is ACCOUNT_TAKEN:
            raise ValidationError(
                "A staff account now exists for this address. Revoke this "
                "invitation and edit that person's roles instead."
            )

        # Mirrors perform_create: a mail failure is reported and audited, not
        # surfaced as a 500. The invitation is untouched either way, so the
        # admin can simply try again once mail is working.
        try:
            send_invitation(invitation, request)
        except Exception:
            record(
                actor=request.user,
                action="invite_send_failed",
                summary=f"Invitation email to {invitation.email} could not be sent",
                detail={"email": invitation.email},
            )
            raise ValidationError(
                "The invitation could not be sent. Check the mail "
                "configuration and try again."
            )

        record(
            actor=request.user,
            action="invite_resent",
            summary=f"{request.user} resent the invitation to {invitation.email}",
            detail={"email": invitation.email},
        )
        return Response({"status": "sent"})

    def perform_destroy(self, instance):
        with transaction.atomic():
            record(
                actor=self.request.user,
                action="invite_revoked",
                summary=f"{self.request.user} revoked the invitation to {instance.email}",
                detail={"email": instance.email},
            )
            instance.delete()


@api_view(["GET", "PATCH"])
@permission_classes([IsAdminUser])
def me(request):
    """The signed-in staff member's own profile. Needs no capability: anyone
    who can open the panel can maintain their own name and phone number."""
    user = request.user
    StaffProfile.objects.get_or_create(user=user)
    user = User.objects.select_related("staff_profile").get(pk=user.pk)
    if request.method == "GET":
        return Response(MeSerializer(user).data)
    serializer = MeSerializer(user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def change_password(request):
    # Checking the current password is a full hash, and a stolen session
    # could otherwise use this to guess it - the password the person may
    # well use elsewhere. Counted per account, not per address.
    if rate_limited(
        request, 'change-password', limit=5, window_seconds=15 * 60,
        subject=f'user:{request.user.pk}',
    ):
        return Response(
            {"detail": "Too many attempts. Please wait 15 minutes and try again."},
            status=429,
        )
    serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    request.user.set_password(serializer.validated_data["new_password"])
    request.user.save(update_fields=["password"])
    # Without this the session hash no longer matches and the next request
    # signs them out of the tab they just changed it from.
    update_session_auth_hash(request._request, request.user)
    return Response({"ok": True})


