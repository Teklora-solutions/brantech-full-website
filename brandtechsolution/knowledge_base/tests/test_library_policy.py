"""Unit and integration tests for Teklora Document Library ACL Policy.

Verifies the complete authorization matrix for Task #33:
- Deny-by-default behavior across all roles and actions
- Deactivation and deletion immediacy
- Strict separation between ownership and administrative approval
- Zero provider calls without processing clearance
- Public vs internal audience boundaries
"""

from django.test import TestCase

from knowledge_base.library.contracts import (
    AccessLevel,
    Audience,
    DocumentVisibility,
    LibraryAction,
    ProcessingClearanceState,
    ProcessingState,
    PublicApprovalState,
)
from knowledge_base.library.policy import LibraryPolicy
from knowledge_base.library.stubs import create_test_scenarios


class LibraryPolicyTests(TestCase):
    def setUp(self):
        scenarios = create_test_scenarios()
        self.store = scenarios["store"]
        self.actors = scenarios["actors"]
        self.docs = scenarios["docs"]
        self.versions = scenarios["versions"]

    # =========================================================================
    # 1. DEACTIVATION & DELETION ENFORCEMENT
    # =========================================================================

    def test_deactivated_account_is_immediately_denied_all_actions(self):
        """Account deactivation must immediately block access with no grace period."""
        deactivated = self.actors["deactivated"]
        doc = self.docs["org"]

        for action in LibraryAction:
            decision = LibraryPolicy.evaluate(
                actor=deactivated,
                document=doc,
                action=action,
                audience=Audience.INTERNAL,
            )
            self.assertFalse(decision.allowed, f"Deactivated user was allowed {action}")
            self.assertEqual(decision.code, "DEACTIVATED_DENIED")

    def test_soft_deleted_document_is_immediately_inaccessible(self):
        """Soft-deleted documents must be blocked across all regular actions."""
        owner = self.actors["owner"]
        admin = self.actors["admin"]
        deleted_doc = self.docs["deleted"]

        for action in [LibraryAction.READ, LibraryAction.DOWNLOAD, LibraryAction.EDIT, LibraryAction.SHARE]:
            dec_owner = LibraryPolicy.evaluate(owner, deleted_doc, action)
            self.assertFalse(dec_owner.allowed)
            self.assertEqual(dec_owner.code, "DOCUMENT_DELETED")

            dec_admin = LibraryPolicy.evaluate(admin, deleted_doc, action)
            self.assertFalse(dec_admin.allowed)
            self.assertEqual(dec_admin.code, "DOCUMENT_DELETED")

    # =========================================================================
    # 2. DOCUMENT OWNERSHIP VS ADMINISTRATOR SEPARATION
    # =========================================================================

    def test_owner_can_read_edit_share_and_delete_own_document(self):
        owner = self.actors["owner"]
        doc = self.docs["private"]

        for action in [LibraryAction.READ, LibraryAction.DOWNLOAD, LibraryAction.EDIT, LibraryAction.SHARE, LibraryAction.DELETE]:
            decision = LibraryPolicy.evaluate(owner, doc, action)
            self.assertTrue(decision.allowed, f"Owner should be allowed {action}: {decision.reason}")

    def test_owner_cannot_approve_public_or_clear_processing(self):
        """Document ownership does NOT confer administrator authority."""
        owner = self.actors["owner"]
        doc = self.docs["private"]

        for action in [LibraryAction.CLEAR_PROCESSING, LibraryAction.APPROVE_PUBLIC, LibraryAction.REVOKE_PUBLIC]:
            decision = LibraryPolicy.evaluate(owner, doc, action)
            self.assertFalse(decision.allowed, f"Owner should NOT be allowed {action}")
            self.assertEqual(decision.code, "ADMIN_REQUIRED")

    def test_administrator_can_clear_processing_and_approve_public(self):
        admin = self.actors["admin"]
        doc = self.docs["private"]

        for action in [LibraryAction.CLEAR_PROCESSING, LibraryAction.APPROVE_PUBLIC, LibraryAction.REVOKE_PUBLIC]:
            decision = LibraryPolicy.evaluate(admin, doc, action)
            self.assertTrue(decision.allowed, f"Admin should be allowed {action}")

    def test_administrator_has_oversight_access_to_private_documents(self):
        admin = self.actors["admin"]
        doc = self.docs["private"]

        for action in [LibraryAction.READ, LibraryAction.DOWNLOAD, LibraryAction.EDIT, LibraryAction.SHARE]:
            decision = LibraryPolicy.evaluate(admin, doc, action)
            self.assertTrue(decision.allowed, f"Admin should have oversight for {action}")

    # =========================================================================
    # 3. DIRECT AND GROUP ACCESS GRANTS
    # =========================================================================

    def test_user_with_read_grant_can_read_and_download_but_not_edit_or_share(self):
        reader = self.actors["reader_user"]
        doc = self.docs["granted"]
        grants = self.store.get_grants(doc.id)

        # Read & download allowed
        for action in [LibraryAction.READ, LibraryAction.DOWNLOAD]:
            decision = LibraryPolicy.evaluate(reader, doc, action, grants=grants)
            self.assertTrue(decision.allowed, f"Reader should be allowed {action}")

        # Edit, share, delete denied
        for action in [LibraryAction.EDIT, LibraryAction.SHARE, LibraryAction.DELETE]:
            decision = LibraryPolicy.evaluate(reader, doc, action, grants=grants)
            self.assertFalse(decision.allowed, f"Reader should NOT be allowed {action}")

    def test_user_with_edit_grant_can_edit_but_cannot_share_or_delete(self):
        """Editors do not implicitly gain sharing, publication, or deletion rights."""
        editor = self.actors["editor_user"]
        doc = self.docs["granted"]
        grants = self.store.get_grants(doc.id)

        # Read, download, edit allowed
        for action in [LibraryAction.READ, LibraryAction.DOWNLOAD, LibraryAction.EDIT]:
            decision = LibraryPolicy.evaluate(editor, doc, action, grants=grants)
            self.assertTrue(decision.allowed, f"Editor should be allowed {action}")

        # Share and delete denied
        for action in [LibraryAction.SHARE, LibraryAction.DELETE]:
            decision = LibraryPolicy.evaluate(editor, doc, action, grants=grants)
            self.assertFalse(decision.allowed, f"Editor should NOT be allowed {action}")
            self.assertEqual(decision.code, "OWNER_OR_ADMIN_REQUIRED")

    def test_group_grant_permits_members_and_denies_non_members(self):
        member = self.actors["group_member"]
        non_member = self.actors["reader_user"]
        doc = self.docs["group"]
        grants = self.store.get_grants(doc.id)

        # Member allowed
        dec_member = LibraryPolicy.evaluate(member, doc, LibraryAction.READ, grants=grants)
        self.assertTrue(dec_member.allowed)

        # Non-member denied
        dec_non_member = LibraryPolicy.evaluate(non_member, doc, LibraryAction.READ, grants=grants)
        self.assertFalse(dec_non_member.allowed)
        self.assertEqual(dec_non_member.code, "NO_ACCESS_GRANT")

    # =========================================================================
    # 4. ORGANISATION VISIBILITY
    # =========================================================================

    def test_organisation_visibility_permits_staff_and_denies_external(self):
        staff_colleague = self.actors["org_staff"]
        external_user = self.actors["unrelated_external"]
        doc = self.docs["org"]

        # Active staff colleague allowed read
        dec_staff = LibraryPolicy.evaluate(staff_colleague, doc, LibraryAction.READ)
        self.assertTrue(dec_staff.allowed)
        self.assertEqual(dec_staff.code, "ALLOWED_ORGANISATION")

        # External non-staff signup account denied
        dec_ext = LibraryPolicy.evaluate(external_user, doc, LibraryAction.READ)
        self.assertFalse(dec_ext.allowed)
        self.assertEqual(dec_ext.code, "STAFF_REQUIRED_FOR_ORG")

    # =========================================================================
    # 5. EXTERNAL PROVIDER CLEARANCE GATE
    # =========================================================================

    def test_zero_provider_calls_without_administrator_clearance(self):
        """No external OCR, embedding, or AI calls before administrator clearance."""
        ver_private = self.versions["private"]  # PENDING clearance
        ver_granted = self.versions["granted"]  # APPROVED clearance

        can_call_uncleared, reason_uncleared = LibraryPolicy.can_call_external_provider(ver_private)
        self.assertFalse(can_call_uncleared)
        self.assertIn("clearance state is 'pending'", reason_uncleared)

        can_call_cleared, reason_cleared = LibraryPolicy.can_call_external_provider(ver_granted)
        self.assertTrue(can_call_cleared)

    # =========================================================================
    # 6. PUBLIC AUDIENCE EVALUATION & PUBLICATION GATE
    # =========================================================================

    def test_public_retrieval_requires_explicit_public_approval(self):
        anonymous = self.actors["anonymous"]

        # 1. Unapproved document
        doc_private = self.docs["private"]
        ver_private = self.versions["private"]
        dec_private = LibraryPolicy.evaluate(
            actor=anonymous,
            document=doc_private,
            action=LibraryAction.READ,
            version=ver_private,
            audience=Audience.PUBLIC,
        )
        self.assertFalse(dec_private.allowed)
        self.assertEqual(dec_private.code, "NOT_PUBLIC_APPROVED")

        # 2. Approved document
        doc_public = self.docs["public"]
        ver_public = self.versions["public"]
        dec_public = LibraryPolicy.evaluate(
            actor=anonymous,
            document=doc_public,
            action=LibraryAction.READ,
            version=ver_public,
            audience=Audience.PUBLIC,
        )
        self.assertTrue(dec_public.allowed)
        self.assertEqual(dec_public.code, "ALLOWED_PUBLIC")

        # 3. Revoked document
        doc_revoked = self.docs["revoked"]
        ver_revoked = self.versions["revoked"]
        dec_revoked = LibraryPolicy.evaluate(
            actor=anonymous,
            document=doc_revoked,
            action=LibraryAction.READ,
            version=ver_revoked,
            audience=Audience.PUBLIC,
        )
        self.assertFalse(dec_revoked.allowed)
        self.assertEqual(dec_revoked.code, "NOT_PUBLIC_APPROVED")

    def test_public_audience_is_forbidden_from_non_read_actions(self):
        """Public audience can never download raw files, edit, share, or delete."""
        anonymous = self.actors["anonymous"]
        doc_public = self.docs["public"]
        ver_public = self.versions["public"]

        for action in [LibraryAction.DOWNLOAD, LibraryAction.EDIT, LibraryAction.SHARE, LibraryAction.DELETE]:
            decision = LibraryPolicy.evaluate(
                actor=anonymous,
                document=doc_public,
                action=action,
                version=ver_public,
                audience=Audience.PUBLIC,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.code, "DENIED_PUBLIC_ACTION")
