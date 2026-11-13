"""Private browser rendering, revocation, bounded conversion and cache lifecycle."""
import fcntl
import io
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from knowledge_base.library import previews
from knowledge_base.library.services import upload_document, mutate
from knowledge_base.models import LibraryAudit, LibraryGrant
from knowledge_base.tasks import maintain_library


class LibraryPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('preview-owner', is_staff=True)
        cls.reader = get_user_model().objects.create_user('preview-reader', is_staff=True)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(LIBRARY_STORAGE_ROOT=directory.name, LIBRARY_PREVIEW_CONVERTER_URL='http://document-preview:3000')
        settings.enable()
        self.addCleanup(settings.disable)
        self.client.force_login(self.owner)
        self.document = self.upload('notes.txt', b'Sanitized browser preview')

    def upload(self, name, data):
        return upload_document(self.owner, SimpleUploadedFile(name, data), title='Preview fixture', authority=True)

    def url(self, document=None):
        doc = document or self.document
        return reverse('library:preview', args=[doc.pk, doc.current_version_id])

    def body(self, response):
        # Django's test streaming wrapper closes the response on exhaustion.
        # Closing it twice emits request_finished outside that wrapper and can
        # close the PostgreSQL connection inside TestCase's outer transaction.
        return b''.join(response.streaming_content) if response.streaming else response.content

    def word(self):
        from docx import Document
        document = Document()
        document.add_heading('Sanitized report', 0)
        document.add_paragraph('A paragraph with a private browser preview.')
        stream = io.BytesIO()
        document.save(stream)
        return self.upload('report.docx', stream.getvalue())

    def converter(self, data=b'%PDF-1.4\nsynthetic response'):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        response = Mock(status_code=200, headers={'Content-Type': 'application/pdf'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = iter([data])
        session.post.return_value = response
        return session, response

    def test_text_preview_before_clearance_no_provider_or_approval_changes(self):
        with patch('knowledge_base.tasks.process_library_version.delay') as enqueue:
            response = self.client.get(self.url())
        self.assertContains(response, 'Sanitized browser preview')
        enqueue.assert_not_called()
        version = self.document.current_version
        version.refresh_from_db()
        self.assertEqual(version.clearance_state, 'pending')
        self.assertEqual(version.processing_state, 'awaiting_clearance')
        self.assertEqual(version.public_approval_state, 'not_reviewed')
        self.assertEqual(LibraryAudit.objects.filter(action='preview', version=version).count(), 1)

    def test_preview_security_headers_and_escaping(self):
        doc = self.upload('reference.md', b'<img src=x onerror=alert(1)> & [bad](javascript:alert(1))')
        response = self.client.get(self.url(doc))
        self.assertContains(response, '&lt;img')
        self.assertNotContains(response, '<img')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn("default-src 'none'", response['Content-Security-Policy'])

    def test_text_preview_is_bounded_and_discloses_truncation(self):
        doc = self.upload('large.txt', b'x' * (previews.TEXT_LIMIT + 100))
        response = self.client.get(self.url(doc))
        self.assertContains(response, 'first 256 KiB')
        self.assertLess(len(response.content), previews.TEXT_LIMIT + 3000)

    def test_native_pdf_and_image_mime_and_inline_disposition(self):
        for name, data, mime in [('report.pdf', b'%PDF-1.4\nfixture', 'application/pdf'),
                                 ('scan.png', b'\x89PNG\r\n\x1a\nfixture', 'image/png'),
                                 ('photo.jpg', b'\xff\xd8\xfffixture', 'image/jpeg')]:
            with self.subTest(name=name):
                doc = self.upload(name, data)
                response = self.client.get(self.url(doc))
                self.assertEqual(response['Content-Type'], mime)
                self.assertTrue(response['Content-Disposition'].startswith('inline;'))
                self.assertEqual(self.body(response), data)
                download = self.client.get(reverse('library:download', args=[doc.pk]))
                self.assertTrue(download['Content-Disposition'].startswith('attachment;'))
                self.body(download)
                if name.endswith('.pdf'):
                    self.assertContains(self.client.get(reverse('library:detail', args=[doc.pk])), 'Read PDF')

    def test_authentication_staff_and_private_acl(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url()).status_code, 302)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        external = get_user_model().objects.create_user('preview-nonstaff')
        self.client.force_login(external)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_user_grant_revocation(self):
        grant = LibraryGrant.objects.create(document=self.document, user=self.reader)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        grant.delete()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_group_revocation(self):
        group = Group.objects.create(name='Preview readers')
        self.reader.groups.add(group)
        LibraryGrant.objects.create(document=self.document, group=group)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.reader.groups.remove(group)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_deleted_blocked_and_inactive_accounts(self):
        version = self.document.current_version
        version.clearance_state = 'blocked'
        version.processing_state = 'blocked'
        version.save()
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.document.is_deleted = True
        self.document.save()
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.owner.is_active = False
        self.owner.save()
        self.assertNotEqual(self.client.get(self.url()).status_code, 200)

    def test_version_identity_and_replacement_are_not_silently_changed(self):
        old_url = self.url()
        mutate(self.owner, self.document.pk, self.document.current_version_id, 'replace',
               data={'authority': True}, upload=SimpleUploadedFile('next.txt', b'New revision'))
        self.assertEqual(self.client.get(old_url).status_code, 404)
        other = self.upload('other.txt', b'Other content')
        forged = reverse('library:preview', args=[self.document.pk, other.current_version_id])
        self.assertEqual(self.client.get(forged).status_code, 404)

    def test_missing_original_and_unsupported_format(self):
        self.document.current_version.original.storage.delete(self.document.current_version.original.name)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        doc = self.upload('other.txt', b'Content')
        doc.current_version.detected_format = 'svg'
        doc.current_version.save()
        self.assertEqual(self.client.get(self.url(doc)).status_code, 404)

    def test_word_conversion_cached_privately_and_reuses_version(self):
        doc = self.word()
        session, _ = self.converter()
        with patch.object(previews.requests, 'Session', return_value=session):
            first = self.client.get(self.url(doc))
            self.assertEqual(first['Content-Type'], 'application/pdf')
            self.assertIn('report.pdf', first['Content-Disposition'])
            self.assertTrue(self.body(first).startswith(b'%PDF-'))
            self.body(self.client.get(self.url(doc)))
        self.assertEqual(session.post.call_count, 1)
        self.assertFalse(session.trust_env)
        self.assertFalse(session.post.call_args.kwargs['allow_redirects'])
        path = previews.preview_path(doc.current_version)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(path.parent.glob('.preview-*')))
        doc.current_version.original.storage.delete(doc.current_version.original.name)
        self.assertEqual(self.client.get(self.url(doc)).status_code, 404)

    def test_unconfigured_or_external_converter_fails_closed(self):
        doc = self.word()
        for url in ['', 'https://docs.google.com', 'http://attacker.example', 'http://localhost/redirect', 'http://user:secret@localhost', 'http://[bad']:
            with self.subTest(url=url), override_settings(LIBRARY_PREVIEW_CONVERTER_URL=url):
                with patch.object(previews.requests, 'Session') as session:
                    response = self.client.get(self.url(doc))
                self.assertContains(response, 'not configured', status_code=503)
                session.assert_not_called()
                self.assertEqual(response['Retry-After'], '5')

    def test_converter_connection_failure_safe_and_original_remains(self):
        doc = self.word()
        session, _ = self.converter()
        session.post.side_effect = requests.Timeout('NEVER_EXPOSE_CONVERTER_DETAIL')
        with patch.object(previews.requests, 'Session', return_value=session):
            response = self.client.get(self.url(doc))
        self.assertContains(response, 'temporarily unavailable', status_code=503)
        self.assertNotContains(response, 'NEVER_EXPOSE_CONVERTER_DETAIL', status_code=503)
        self.assertTrue(Path(doc.current_version.original.path).exists())
        self.assertFalse(previews.preview_path(doc.current_version).exists())

    def test_converter_redirect_wrong_mime_and_invalid_output(self):
        doc = self.word()
        for status, mime, body in [(302, 'application/pdf', b'%PDF-'), (200, 'text/html', b'<html>'), (200, 'application/pdf', b'not a pdf')]:
            with self.subTest(status=status, mime=mime):
                session, response = self.converter(body)
                response.status_code = status
                response.headers['Content-Type'] = mime
                with patch.object(previews.requests, 'Session', return_value=session):
                    self.assertEqual(self.client.get(self.url(doc)).status_code, 503)
                self.assertFalse(previews.preview_path(doc.current_version).exists())
                self.assertFalse(list(previews.preview_path(doc.current_version).parent.glob('.preview-*')))

    def test_converter_output_size_is_bounded(self):
        doc = self.word()
        session, _ = self.converter(b'%PDF-' + b'x' * previews.MAX_UPLOAD)
        with patch.object(previews.requests, 'Session', return_value=session):
            self.assertContains(self.client.get(self.url(doc)), 'safe size', status_code=503)
        self.assertFalse(previews.preview_path(doc.current_version).exists())

    def test_conversion_singleflight(self):
        doc = self.word()
        path = previews.preview_path(doc.current_version)
        path.parent.mkdir(mode=0o700)
        with open(path.with_suffix('.lock'), 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertContains(self.client.get(self.url(doc)), 'being prepared', status_code=503)

    def test_permission_rechecked_after_slow_conversion(self):
        doc = self.word()
        grant = LibraryGrant.objects.create(document=doc, user=self.reader)
        path = previews.preview_path(doc.current_version)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b'%PDF-fixture')
        def revoke(_):
            grant.delete()
            return path
        self.client.force_login(self.reader)
        with patch('knowledge_base.views.docx_pdf', side_effect=revoke):
            self.assertEqual(self.client.get(self.url(doc)).status_code, 404)

    def test_account_rechecked_after_slow_conversion(self):
        doc = self.word()
        path = previews.preview_path(doc.current_version)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b'%PDF-fixture')
        def deactivate(_):
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return path
        with patch('knowledge_base.views.docx_pdf', side_effect=deactivate):
            self.assertEqual(self.client.get(self.url(doc)).status_code, 403)

    def test_corrupt_original_never_reaches_converter(self):
        doc = self.word()
        Path(doc.current_version.original.path).write_bytes(b'corrupt archive')
        with patch.object(previews.requests, 'Session') as session:
            self.assertContains(self.client.get(self.url(doc)), 'could not be verified', status_code=503)
        session.assert_not_called()

    def test_purge_removes_derivatives_and_cleans_orphans(self):
        doc = self.word()
        path = previews.preview_path(doc.current_version)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b'%PDF-fixture')
        orphan = path.parent / ('999999-' + 'a' * 64 + '.pdf')
        orphan.write_bytes(b'%PDF-old orphan')
        old = timezone.now().timestamp() - 2 * 86400
        os.utime(orphan, (old, old))
        doc.is_deleted = True
        doc.save()
        maintain_library()
        self.assertFalse(path.exists())
        self.assertFalse(orphan.exists())

    def test_detail_embeds_reader_and_keeps_download_and_extracted_text(self):
        response = self.client.get(reverse('library:detail', args=[self.document.pk]))
        self.assertContains(response, '<iframe')
        self.assertContains(response, self.url())
        self.assertContains(response, 'Download original')
        self.assertContains(response, 'Searchable extracted text')
