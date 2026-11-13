"""Private exact-version task evidence, lifecycle and automation regressions."""
import tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, Client, override_settings, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from knowledge_base.library.access import visible_documents
from knowledge_base.library.services import upload_document, mutate
from knowledge_base.models import LibraryGrant, LibraryVersion, LibraryAudit
from knowledge_base.tasks import maintain_library
from tasks import deliverables
from tasks.github import finish_task
from tasks.models import Task, TaskAssignment, TaskSubmission, TaskSubmissionReview, TaskCommit


class DeliverableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.owner = user.objects.create_user('author', is_staff=True)
        cls.peer = user.objects.create_user('peer', is_staff=True)
        cls.outsider = user.objects.create_user('outsider', is_staff=True)
        cls.manager = user.objects.create_user('reviewer', is_staff=True)
        cls.manager.user_permissions.add(Permission.objects.get(codename='manage_tasks'))

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(LIBRARY_STORAGE_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.task = Task.objects.create(title='Research', delivery_requirement='document')
        self.assignment = TaskAssignment.objects.create(task=self.task, user=self.owner)
        self.document = self.upload()
        self.version = self.document.current_version
        self.client.force_login(self.owner)
        self.url = f'/api/work/tasks/{self.task.pk}/'

    def upload(self, name='report.txt', body=b'Private task report'):
        return upload_document(self.owner, SimpleUploadedFile(name, body), title='Private report title', authority=True)

    def payload(self, **changes):
        latest = deliverables.current_submission(self.assignment)
        data = dict(version_ids=[self.version.pk], note='Private submission note', expected_submission_id=latest.pk if latest else None,
                    request_id=str(uuid4()), share_confirmation=True)
        data.update(changes)
        return data

    def submit(self, **changes):
        return deliverables.submit(self.task.pk, self.owner, self.payload(**changes))

    def review(self, submission, decision='accepted', feedback='Reviewed original'):
        return deliverables.review(self.task.pk, self.manager,
            {'submission_id': submission.pk, 'decision': decision, 'feedback': feedback})

    def post(self, endpoint, data=None):
        return self.client.post(self.url + endpoint + '/', data or {}, content_type='application/json')

    def test_document_completion_guard_applies_to_assignee_and_manager(self):
        self.assertEqual(self.post('complete').status_code, 400)
        self.client.force_login(self.manager)
        self.assertEqual(self.post('complete', {'assignee_id': self.owner.pk}).status_code, 400)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.completed_at)

    def test_submit_freezes_original_and_requires_separate_acceptance_and_approval(self):
        response = self.post('deliverables', self.payload())
        self.assertEqual(response.status_code, 201, response.data)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.IN_REVIEW)
        self.version.refresh_from_db()
        self.assertEqual(self.version.clearance_state, 'pending')
        self.assertEqual(self.version.public_approval_state, 'not_reviewed')
        consent = LibraryAudit.objects.get(action='task_evidence_submitted')
        self.assertEqual(consent.details['review_audience'], 'active_manage_tasks')
        self.assertNotIn('Private submission note', str(consent.details))
        self.client.force_login(self.manager)
        self.assertEqual(self.post('approve').status_code, 400)
        self.review(TaskSubmission.objects.get())
        self.assertEqual(self.post('approve').status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.DONE)

    def test_multi_file_and_idempotent_retry(self):
        second = self.upload('other.txt').current_version
        data = self.payload(version_ids=[self.version.pk, second.pk])
        with patch('tasks.emails.notify_deliverable_event') as notify:
            with self.captureOnCommitCallbacks(execute=True):
                first = deliverables.submit(self.task.pk, self.owner, data)
                retry = deliverables.submit(self.task.pk, self.owner, data)
            self.assertEqual(notify.call_count, 1)
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(first.attachments.count(), 2)
        self.assertEqual(TaskSubmission.objects.count(), 1)

    def test_multi_assignee_changes_are_targeted_and_history_is_append_only(self):
        peer_assignment = TaskAssignment.objects.create(task=self.task, user=self.peer, completed_at=timezone.now())
        submission = self.submit()
        self.review(submission, 'changes_requested', 'Add evidence for pricing')
        self.task.refresh_from_db()
        peer_assignment.refresh_from_db()
        self.assignment.refresh_from_db()
        self.assertEqual(self.task.status, Task.OPEN)
        self.assertIsNotNone(peer_assignment.completed_at)
        self.assertIsNone(self.assignment.completed_at)
        with self.assertRaises(ValidationError):
            self.review(submission)
        revision = self.submit(note='Updated research')
        self.assertEqual(revision.revision, 2)
        self.assertEqual(submission.reviews.get().feedback, 'Add evidence for pricing')
        self.assertEqual(TaskSubmission.objects.get(pk=submission.pk).note, 'Private submission note')
        with self.assertRaises(ValidationError):
            self.review(submission)

    def test_missing_feedback_and_sharing_confirmation_are_rejected(self):
        self.assertEqual(self.post('deliverables', self.payload(share_confirmation=False)).status_code, 400)
        submission = self.submit()
        with self.assertRaises(ValidationError):
            self.review(submission, 'changes_requested', '')

    def test_stale_submission_or_replaced_selection_is_rejected(self):
        stale = self.payload()
        self.submit()
        self.assertEqual(self.post('deliverables', stale).status_code, 400)
        mutate(self.owner, self.document.pk, self.version.pk, 'replace', data={'authority': True},
               upload=SimpleUploadedFile('new.txt', b'New original'))
        self.assertEqual(self.post('deliverables', self.payload()).status_code, 400)

    def test_read_and_edit_grants_cannot_be_submitted_without_share_authority(self):
        for access in ('read', 'edit'):
            LibraryGrant.objects.update_or_create(document=self.document, user=self.peer, defaults={'access_level': access})
            TaskAssignment.objects.get_or_create(task=self.task, user=self.peer)
            self.client.force_login(self.peer)
            self.assertEqual(self.post('deliverables', self.payload()).status_code, 400)
            self.assertEqual(self.client.get(self.url + 'deliverable-documents/').json()['results'], [])

    def test_private_history_and_files_hidden_from_peers_and_board_serializer(self):
        submission = self.submit()
        attachment = submission.attachments.get()
        TaskAssignment.objects.create(task=self.task, user=self.peer)
        for actor in (self.peer, self.outsider):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url + 'deliverables/').json(), [])
            self.assertEqual(self.client.get(self.url + f'deliverable-file/{attachment.pk}/').status_code, 404)
            self.assertNotIn('Private submission note', self.client.get(self.url).content.decode())
            self.assertNotIn('Private submission note', self.client.get(self.url + 'activity/').content.decode())
        self.client.force_login(self.manager)
        self.assertEqual(len(self.client.get(self.url + 'deliverables/').json()), 1)
        self.assertFalse(visible_documents(self.manager).filter(pk=self.document.pk).exists())

    def test_pinned_download_survives_replacement_without_granting_other_versions(self):
        attachment = self.submit().attachments.get()
        mutate(self.owner, self.document.pk, self.version.pk, 'replace', data={'authority': True},
               upload=SimpleUploadedFile('new.txt', b'Replaced private original'))
        self.client.force_login(self.manager)
        response = self.client.get(self.url + f'deliverable-file/{attachment.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'Private task report')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(f'/library/{self.document.pk}/download/').status_code, 404)
        self.review(attachment.submission)

    def test_unassignment_reassignment_and_account_removal_do_not_inherit_evidence(self):
        submission = self.submit()
        self.assignment.delete()
        submission.refresh_from_db()
        self.assertIsNone(submission.assignment_id)
        self.assertEqual(self.client.get(self.url + 'deliverables/').json(), [])
        replacement = TaskAssignment.objects.create(task=self.task, user=self.owner)
        self.assertIsNone(deliverables.current_submission(replacement))
        with self.assertRaises(ValidationError):
            deliverables.validate_completion(replacement)
        # Existing library owner/uploader PROTECT rules require document removal first.
        self.document.delete()
        self.owner.delete()
        submission.refresh_from_db()
        self.assertIsNone(submission.submitter_id)

    def test_deleted_evidence_blocks_pending_approval_and_purge_retains_history(self):
        submission = self.submit()
        self.review(submission)
        mutate(self.owner, self.document.pk, self.version.pk, 'delete')
        self.client.force_login(self.manager)
        self.assertEqual(self.post('approve').status_code, 400)
        self.assertEqual(self.client.get(self.url + f'deliverable-file/{submission.attachments.get().pk}/').status_code, 404)
        original = Path(self.version.original.path)
        maintain_library()
        self.assertFalse(original.exists())
        submission.refresh_from_db()
        self.assertTrue(TaskSubmissionReview.objects.filter(submission=submission).exists())
        self.assertIsNone(submission.attachments.get().version_id)
        self.assertFalse(self.client.get(self.url + 'deliverables/').json()[0]['attachments'][0]['available'])

    def test_missing_original_blocks_review(self):
        submission = self.submit()
        self.version.original.delete(save=False)
        with self.assertRaises(ValidationError):
            self.review(submission)

    def test_manager_capability_revocation_and_deactivation_revoke_access(self):
        attachment = self.submit().attachments.get()
        self.client.force_login(self.manager)
        self.manager.user_permissions.clear()
        self.assertEqual(self.client.get(self.url + f'deliverable-file/{attachment.pk}/').status_code, 404)
        self.client.force_login(self.owner)
        self.owner.is_active = False
        self.owner.save(update_fields=['is_active'])
        self.assertIn(self.client.get(self.url + 'deliverables/').status_code, (401, 403))

    def test_done_task_rejects_submission_upload_review_until_reopened(self):
        submission = self.submit()
        self.review(submission)
        self.client.force_login(self.manager)
        self.assertEqual(self.post('approve').status_code, 200)
        self.assertEqual(self.post('review-deliverable', {'submission_id': submission.pk, 'decision':'changes_requested', 'feedback':'More'}).status_code, 400)
        self.client.force_login(self.owner)
        self.assertEqual(self.post('deliverables', self.payload()).status_code, 400)
        self.assertEqual(self.client.post(self.url + 'deliverable-upload/', {}).status_code, 400)
        self.client.force_login(self.manager)
        self.assertEqual(self.post('reopen', {'reason':'New requirements'}).status_code, 200)
        self.assertEqual(submission.review_state, 'changes_requested')

    def test_upload_is_separate_and_preserved_after_failed_submission(self):
        response = self.client.post(self.url + 'deliverable-upload/', {
            'title':'Uploaded deliverable', 'authority':'true', 'original':SimpleUploadedFile('upload.txt', b'Uploaded report')})
        self.assertEqual(response.status_code, 201, response.data)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.completed_at)
        self.assertEqual(self.post('deliverables', self.payload(version_ids=[response.data['version_id']], share_confirmation=False)).status_code, 400)
        self.assertTrue(LibraryVersion.objects.filter(pk=response.data['version_id']).exists())

    def test_upload_validation_and_non_assignee_access(self):
        self.assertEqual(self.client.post(self.url + 'deliverable-upload/', {'title':'Invalid','original':SimpleUploadedFile('bad.exe', b'invalid')}).status_code, 400)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url + 'deliverable-documents/').status_code, 403)
        self.assertEqual(self.post('deliverables', self.payload()).status_code, 403)
        self.assertEqual(self.client.post(self.url + 'deliverable-upload/', {}).status_code, 403)

    def test_csrf_is_required_for_session_uploads_and_submissions(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url + 'deliverables/', self.payload(), content_type='application/json').status_code, 403)
        self.assertEqual(client.post(self.url + 'deliverable-upload/', {}).status_code, 403)

    def test_automation_does_not_bypass_document_requirement(self):
        with self.assertRaises(ValidationError):
            deliverables.validate_completion(self.assignment)
        self.assertFalse(finish_task(self.task, self.owner, 'Closing commit'))
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.completed_at)

    def test_code_and_either_evidence_are_assignee_specific(self):
        self.task.delivery_requirement = 'code'
        self.task.save()
        TaskCommit.objects.create(task=self.task, sha='a' * 40, author=self.peer, on_default_branch=True)
        self.assertEqual(self.post('complete').status_code, 400)
        TaskCommit.objects.create(task=self.task, sha='b' * 40, author=self.owner, on_default_branch=False)
        self.assertEqual(self.post('complete').status_code, 400)
        TaskCommit.objects.filter(author=self.owner).update(on_default_branch=True)
        peer = TaskAssignment.objects.create(task=self.task, user=self.peer)
        self.assertFalse(finish_task(self.task, self.owner, 'Merged'))
        peer.refresh_from_db()
        self.assertIsNone(peer.completed_at)
        self.assignment.refresh_from_db()
        self.assertIsNotNone(self.assignment.completed_at)
        self.task.delivery_requirement = 'either'
        self.task.save()
        self.assertEqual(self.post('complete').status_code, 200)

    def test_legacy_completion_still_works_but_attached_work_requires_review(self):
        self.task.delivery_requirement = 'standard'
        self.task.save()
        self.assertEqual(self.post('complete').status_code, 200)
        self.submit()
        self.client.force_login(self.manager)
        self.assertEqual(self.post('approve').status_code, 400)

    def test_api_key_mcp_completion_uses_the_same_document_guard(self):
        from staff.models import DeveloperApiKey
        _, key = DeveloperApiKey.generate_key(self.owner, 'isolated-test')
        self.client.logout()
        response = self.client.post(self.url + 'complete/', {}, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {key}')
        self.assertEqual(response.status_code, 400)
        self.submit()
        response = self.client.post(self.url + 'complete/', {}, content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {key}')
        self.assertEqual(response.status_code, 200)

    def test_picker_is_paginated_and_searchable(self):
        for i in range(21):
            self.upload(f'report-{i}.txt')
        page = self.client.get(self.url + 'deliverable-documents/').json()
        self.assertEqual(len(page['results']), 20)
        self.assertEqual(page['next_page'], 2)
        self.assertEqual(self.client.get(self.url + 'deliverable-documents/?q=not-present').json()['results'], [])

    def test_requirement_change_cannot_invalidate_submitted_work(self):
        self.submit()
        self.client.force_login(self.manager)
        self.assertEqual(self.client.patch(self.url, {'delivery_requirement':'standard'}, content_type='application/json').status_code, 400)


class ConcurrentSubmissionTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_assignees_finish_concurrently_without_losing_review_transition(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        users = [get_user_model().objects.create_user(f'parallel-{i}', is_staff=True) for i in range(2)]
        task = Task.objects.create(title='Parallel reports', delivery_requirement='document')
        for user in users:
            TaskAssignment.objects.create(task=task, user=user)
        with tempfile.TemporaryDirectory() as root, override_settings(LIBRARY_STORAGE_ROOT=root):
            versions = [upload_document(user, SimpleUploadedFile('report.txt', b'Sanitized report'), title='Report', authority=True).current_version_id for user in users]
            def send(index):
                try:
                    return deliverables.submit(task.pk, users[index], {
                        'version_ids':[versions[index]], 'expected_submission_id':None,
                        'request_id':str(uuid4()), 'share_confirmation':True,
                    }).pk
                finally:
                    connections.close_all()
            with patch('tasks.emails.notify_deliverable_event'):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(len(set(pool.map(send, range(2)))), 2)
            task.refresh_from_db()
            self.assertEqual(task.status, Task.IN_REVIEW)
            self.assertEqual(task.assignments.filter(completed_at__isnull=False).count(), 2)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_retry_creates_one_round_and_one_notification(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        user = get_user_model().objects.create_user('concurrent-author', is_staff=True)
        task = Task.objects.create(title='Concurrent report', delivery_requirement='document')
        TaskAssignment.objects.create(task=task, user=user)
        with tempfile.TemporaryDirectory() as root, override_settings(LIBRARY_STORAGE_ROOT=root):
            document = upload_document(user, SimpleUploadedFile('report.txt', b'Sanitized report'), title='Report', authority=True)
            data = {'version_ids':[document.current_version_id], 'expected_submission_id':None,
                    'request_id':str(uuid4()), 'share_confirmation':True}
            def send():
                try:
                    actor = get_user_model().objects.get(pk=user.pk)
                    return deliverables.submit(task.pk, actor, data).pk
                finally:
                    connections.close_all()
            with patch('tasks.emails.notify_deliverable_event') as notify:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    ids = list(pool.map(lambda _: send(), range(2)))
                self.assertEqual(ids[0], ids[1])
                self.assertEqual(TaskSubmission.objects.filter(task=task).count(), 1)
                self.assertEqual(notify.call_count, 1)
