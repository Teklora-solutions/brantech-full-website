"""Private rendering only: no provider processing or publication decisions."""
import fcntl
import hashlib
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit

import requests
from django.conf import settings

from .parsers import MAX_UPLOAD
from .storage import library_storage

logger = logging.getLogger(__name__)
TEXT_LIMIT = 256 * 1024
PREVIEW_MIME = {'pdf': 'application/pdf', 'docx': 'application/pdf',
                'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'txt': 'text/plain', 'md': 'text/plain'}


class PreviewUnavailable(Exception):
    """A safe explanation suitable for the private reader, never converter output."""


def preview_path(version):
    if not re.fullmatch(r'[0-9a-f]{64}', version.checksum_sha256):
        raise PreviewUnavailable('The document checksum is invalid. Download the original instead.')
    return Path(library_storage.location) / 'previews' / f'{version.pk}-{version.checksum_sha256}.pdf'


def _converter_url():
    base = settings.LIBRARY_PREVIEW_CONVERTER_URL
    try:
        parsed = urlsplit(base)
    except ValueError as exc:
        raise PreviewUnavailable('Word preview conversion is not configured. Download the original instead.') from exc
    if (parsed.scheme != 'http' or parsed.hostname not in {'document-preview', 'localhost', '127.0.0.1'}
            or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise PreviewUnavailable('Word preview conversion is not configured. Download the original instead.')
    return base.rstrip('/') + '/forms/libreoffice/convert'


def docx_pdf(version):
    """Atomically cache one bounded conversion; no shared credentials or public URLs."""
    target = preview_path(version)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Keep lock inodes until scheduled orphan cleanup; unlinking a live lock
    # would let another process acquire a different inode for the same version.
    with open(target.with_suffix('.lock'), 'a+b') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PreviewUnavailable('This Word preview is being prepared. Retry shortly, or download the original.') from exc
        if target.is_file():
            return target
        url = _converter_url()
        with version.original.open('rb') as original:
            data = original.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD or hashlib.sha256(data).hexdigest() != version.checksum_sha256:
            raise PreviewUnavailable('The original could not be verified. Download it or contact an administrator.')
        temp_name = None
        try:
            # Disable environment proxies/auth and redirects. Only our explicitly
            # allowlisted private/loopback service receives the sanitized filename.
            with requests.Session() as session:
                session.trust_env = False
                deadline = time.monotonic() + 60
                with session.post(url, files={'files': ('document.docx', data,
                                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},
                                  timeout=(3, 45), stream=True, allow_redirects=False) as response:
                    if response.status_code != 200 or response.headers.get('Content-Type', '').split(';')[0] != 'application/pdf':
                        raise PreviewUnavailable('Word preview conversion failed. Retry or download the original.')
                    total = 0
                    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.preview-', delete=False) as output:
                        temp_name = output.name
                        signature = b''
                        for chunk in response.iter_content(64 * 1024):
                            total += len(chunk)
                            if total > MAX_UPLOAD or time.monotonic() > deadline:
                                raise PreviewUnavailable('The Word preview exceeded its safe size or time limit.')
                            signature = (signature + chunk)[:5]
                            output.write(chunk)
                        if signature != b'%PDF-':
                            raise PreviewUnavailable('The converter did not produce a valid PDF. Download the original instead.')
                    os.replace(temp_name, target)
                    temp_name = None
        except requests.RequestException as exc:
            logger.warning('Library preview converter unavailable: version=%s type=%s', version.pk, type(exc).__name__)
            raise PreviewUnavailable('Word preview conversion is temporarily unavailable. Retry or download the original.') from None
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)
    return target


def purge_preview(version):
    """Originals and derived files have the same deletion/retention lifecycle."""
    root = Path(library_storage.location) / 'previews'
    for path in root.glob(f'{version.pk}-*.pdf'):
        path.unlink(missing_ok=True)
    # Lock files contain no document bytes. Orphan cleanup removes these after
    # the version disappears, without breaking singleflight during conversion.


def clean_orphan_previews(cutoff):
    from knowledge_base.models import LibraryVersion
    root = Path(library_storage.location) / 'previews'
    cleaned = 0
    for path in root.glob('*'):
        if not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        match = re.fullmatch(r'(\d+)-([0-9a-f]{64})\.(pdf|lock)', path.name)
        orphan = not match or not LibraryVersion.objects.filter(pk=match[1], checksum_sha256=match[2]).exists()
        if orphan:
            path.unlink(missing_ok=True)
            cleaned += 1
            if cleaned >= 500:
                break
