"""Teklora Document Library Access Control Policy Engine.

Pure, deterministic, deny-by-default authorization logic enforcing:
- Immediate revocation upon account deactivation or document deletion.
- Strict separation between document ownership and administrator capabilities.
- Zero external provider processing without administrator clearance.
- No public retrieval without explicit publication approval on the current version.
- Reusable policy evaluation for listing, viewing, downloading, editing, sharing,
  and AI retrieval.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Set, Union

from .contracts import (
    AccessLevel,
    Audience,
    DocumentContract,
    DocumentVisibility,
    GrantContract,
    LibraryAction,
    PolicyDecision,
    ProcessingClearanceState,
    ProcessingState,
    PublicApprovalState,
    VersionContract,
)

ADMIN_CAPABILITY = "approve_library_publication"
ADMIN_GROUP_NAME = "Administrator"


class LibraryPolicy:
    """Canonical authorization engine for the Teklora Document Library."""

    @classmethod
    def is_administrator(cls, actor: Any) -> bool:
        """Verify whether an actor holds canonical administrator approval authority.
        
        Rule: Active superuser OR active staff member in the canonical
        Administrator group possessing approval authority. Document ownership
        never confers administrator status.
        """
        if actor is None:
            return False

        # Active check
        if not getattr(actor, "is_active", False):
            return False

        # Superuser override
        if getattr(actor, "is_superuser", False):
            return True

        # Group and capability checks
        groups = getattr(actor, "groups", None)
        if groups is not None:
            if hasattr(groups, "filter"):
                in_admin_group = groups.filter(name=ADMIN_GROUP_NAME).exists()
            elif hasattr(groups, "values_list"):
                in_admin_group = ADMIN_GROUP_NAME in groups.values_list("name", flat=True)
            elif isinstance(groups, (list, tuple, set)):
                in_admin_group = any(
                    (g.name if hasattr(g, "name") else str(g)) == ADMIN_GROUP_NAME
                    for g in groups
                )
            else:
                in_admin_group = False

            if in_admin_group:
                # If actor has Django's has_perm, check specific capability or fall back to preset
                has_perm = getattr(actor, "has_perm", None)
                if callable(has_perm):
                    if has_perm(f"staff.{ADMIN_CAPABILITY}") or has_perm("staff.manage_staff"):
                        return True
                return True

        return False

    @classmethod
    def is_owner(cls, actor: Any, document: Any) -> bool:
        """Check if actor is the authenticated, active owner of the document."""
        if actor is None or not getattr(actor, "is_active", False):
            return False
        if getattr(actor, "is_anonymous", False):
            return False

        actor_id = getattr(actor, "id", getattr(actor, "pk", None))
        owner_id = getattr(document, "owner_id", None)
        if owner_id is None and hasattr(document, "owner"):
            owner_id = getattr(document.owner, "id", None)

        return actor_id is not None and actor_id == owner_id

    @classmethod
    def evaluate(
        cls,
        actor: Any,
        document: Any,
        action: LibraryAction,
        version: Optional[Any] = None,
        audience: Audience = Audience.INTERNAL,
        grants: Optional[Iterable[Any]] = None,
    ) -> PolicyDecision:
        """Evaluate access to a document or action with deny-by-default enforcement."""
        # 1. Soft-deleted documents deny all regular actions
        is_deleted = getattr(document, "is_deleted", False)
        if is_deleted:
            return PolicyDecision.deny(
                "DOCUMENT_DELETED",
                "Document has been deleted and cannot be accessed or retrieved.",
            )

        # 2. Public Audience Evaluation
        if audience == Audience.PUBLIC:
            if action != LibraryAction.READ:
                return PolicyDecision.deny(
                    "DENIED_PUBLIC_ACTION",
                    f"Action '{action}' is strictly prohibited for public audience context.",
                )

            # Public retrieval strictly requires version approval
            target_version = version or getattr(document, "current_version", None)
            if target_version is None:
                return PolicyDecision.deny(
                    "NO_VERSION_FOR_PUBLIC",
                    "Document has no active version eligible for public retrieval.",
                )

            approval_state = getattr(target_version, "public_approval_state", None)
            if approval_state != PublicApprovalState.APPROVED:
                return PolicyDecision.deny(
                    "NOT_PUBLIC_APPROVED",
                    f"Document version is not approved for public retrieval (current state: {approval_state}).",
                )

            proc_state = getattr(target_version, "processing_state", None)
            if proc_state != ProcessingState.READY:
                return PolicyDecision.deny(
                    "PROCESSING_NOT_READY",
                    f"Document version is not ready for retrieval (processing state: {proc_state}).",
                )

            return PolicyDecision.allow(
                "ALLOWED_PUBLIC",
                "Document version is approved and ready for public retrieval.",
            )

        # 3. Internal Audience Evaluation
        # Authenticated & active check
        if (
            actor is None
            or not getattr(actor, "is_authenticated", False)
            or getattr(actor, "is_anonymous", False)
        ):
            return PolicyDecision.deny(
                "ANONYMOUS_DENIED",
                "Authentication is required to access internal library documents.",
            )

        if not getattr(actor, "is_active", False):
            return PolicyDecision.deny(
                "DEACTIVATED_DENIED",
                "Account is deactivated; all document access is immediately denied.",
            )

        is_admin = cls.is_administrator(actor)
        is_own = cls.is_owner(actor, document)

        # 3a. Administrative-only actions
        if action in (
            LibraryAction.CLEAR_PROCESSING,
            LibraryAction.APPROVE_PUBLIC,
            LibraryAction.REVOKE_PUBLIC,
        ):
            if is_admin:
                return PolicyDecision.allow(
                    "ALLOWED_ADMIN",
                    f"Administrator clearance/approval permitted for action '{action}'.",
                )
            return PolicyDecision.deny(
                "ADMIN_REQUIRED",
                "Administrator approval capability is required. Document ownership does not grant administrative authority.",
            )

        # 3b. Share and Delete actions (Owner or Administrator only)
        if action in (LibraryAction.SHARE, LibraryAction.DELETE):
            if is_own or is_admin:
                return PolicyDecision.allow(
                    "ALLOWED_OWNER_OR_ADMIN",
                    f"Action '{action}' permitted for document owner or administrator.",
                )
            return PolicyDecision.deny(
                "OWNER_OR_ADMIN_REQUIRED",
                f"Action '{action}' is restricted to the document owner or an administrator.",
            )

        # 3c. Edit action
        if action == LibraryAction.EDIT:
            if is_own or is_admin:
                return PolicyDecision.allow(
                    "ALLOWED_EDIT_AUTHORITY",
                    "Edit permitted for document owner or administrator.",
                )
            # Check explicit EDIT grant
            if cls._has_grant(actor, document, grants, required_level=AccessLevel.EDIT):
                return PolicyDecision.allow(
                    "ALLOWED_EDIT_GRANT",
                    "Explicit edit grant granted to user or group.",
                )
            return PolicyDecision.deny(
                "EDIT_GRANT_REQUIRED",
                "Edit access requires document ownership, administrator privileges, or an explicit edit grant.",
            )

        # 3d. Read and Download actions
        if action in (LibraryAction.READ, LibraryAction.DOWNLOAD):
            if is_own or is_admin:
                return PolicyDecision.allow(
                    "ALLOWED_READ_AUTHORITY",
                    "Read/download permitted for document owner or administrator.",
                )

            # Explicit grant (either READ or EDIT grants read access)
            if cls._has_grant(actor, document, grants, required_level=AccessLevel.READ):
                return PolicyDecision.allow(
                    "ALLOWED_READ_GRANT",
                    "Explicit read/edit grant assigned to user or user's group.",
                )

            # Organisation visibility check: requires active staff member
            doc_visibility = getattr(document, "visibility", None)
            if doc_visibility == DocumentVisibility.ORGANISATION:
                if getattr(actor, "is_staff", False):
                    return PolicyDecision.allow(
                        "ALLOWED_ORGANISATION",
                        "Document is shared with organisation staff.",
                    )
                return PolicyDecision.deny(
                    "STAFF_REQUIRED_FOR_ORG",
                    "Organisation documents are restricted to authenticated staff members.",
                )

            return PolicyDecision.deny(
                "NO_ACCESS_GRANT",
                "No read grant, ownership, or organisation access for this document.",
            )

        return PolicyDecision.deny("DENY_DEFAULT", f"Unhandled action '{action}' denied by default.")

    @classmethod
    def can_call_external_provider(cls, version: Any) -> tuple[bool, str]:
        """Strict gate: zero external provider calls (OCR/embedding/AI) without clearance."""
        if version is None:
            return False, "No version specified for provider check."

        clearance = getattr(version, "clearance_state", None)
        clearance_val = getattr(clearance, "value", str(clearance) if clearance is not None else "none")
        if clearance != ProcessingClearanceState.APPROVED and clearance_val != "approved":
            return (
                False,
                f"External provider processing is blocked: clearance state is '{clearance_val}'. Administrator clearance is required.",
            )

        proc_state = getattr(version, "processing_state", None)
        proc_val = getattr(proc_state, "value", str(proc_state) if proc_state is not None else "")
        if proc_state == ProcessingState.BLOCKED or proc_val == "blocked":
            return False, "Version processing is blocked by policy."

        return True, "External provider processing is authorized."

    @classmethod
    def _has_grant(
        cls,
        actor: Any,
        document: Any,
        grants: Optional[Iterable[Any]],
        required_level: AccessLevel = AccessLevel.READ,
    ) -> bool:
        """Check whether actor has a valid user-level or group-level grant."""
        actor_id = getattr(actor, "id", getattr(actor, "pk", None))
        if actor_id is None:
            return False

        # Collect actor's group IDs
        actor_group_ids: Set[int] = set()
        groups = getattr(actor, "groups", None)
        if groups is not None:
            if hasattr(groups, "values_list"):
                actor_group_ids = set(groups.values_list("id", flat=True))
            elif isinstance(groups, (list, tuple, set)):
                for g in groups:
                    gid = getattr(g, "id", getattr(g, "pk", None))
                    if gid is not None:
                        actor_group_ids.add(gid)

        # Inspect provided grants or model relation
        active_grants = grants
        if active_grants is None and hasattr(document, "grants"):
            if hasattr(document.grants, "all"):
                active_grants = document.grants.all()
            elif isinstance(document.grants, (list, tuple, set)):
                active_grants = document.grants

        if not active_grants:
            return False

        for g in active_grants:
            g_level = getattr(g, "access_level", AccessLevel.READ)
            # EDIT level satisfies READ requirement; READ does not satisfy EDIT requirement
            if required_level == AccessLevel.EDIT and g_level != AccessLevel.EDIT:
                continue

            # User grant
            g_user_id = getattr(g, "user_id", None)
            if g_user_id is None and hasattr(g, "user") and g.user is not None:
                g_user_id = getattr(g.user, "id", None)
            if g_user_id == actor_id:
                return True

            # Group grant
            g_group_id = getattr(g, "group_id", None)
            if g_group_id is None and hasattr(g, "group") and g.group is not None:
                g_group_id = getattr(g.group, "id", None)
            if g_group_id is not None and g_group_id in actor_group_ids:
                return True

        return False
