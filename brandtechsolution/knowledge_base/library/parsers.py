"""Bounded local validation/extraction. Uploaded content is untrusted evidence."""
import hashlib
import io
from pathlib import Path
import subprocess
import tempfile
import zipfile

from django.core.exceptions import ValidationError

MAX_UPLOAD = 25 * 1024 * 1024
MAX_TEXT = 10 * 1024 * 1024
MAX_PAGES = 30
MAX_CHUNKS = 500
FORMATS = {'pdf', 'docx', 'txt', 'md', 'png', 'jpg', 'jpeg'}


def validate_upload(upload):
    if not upload or not 0 < upload.size <= MAX_UPLOAD:
        raise ValidationError('Choose a document between 1 byte and 25 MB.')
    name = Path(upload.name.replace('\\', '/')).name[:255]
    fmt = name.rsplit('.', 1)[-1].lower()
    if fmt not in FORMATS:
        raise ValidationError('Supported files: PDF, DOCX, TXT, Markdown, PNG and JPEG. No recordings.')
    data = upload.read(MAX_UPLOAD + 1)
    upload.seek(0)
    if len(data) > MAX_UPLOAD:
        raise ValidationError('Document exceeds 25 MB.')
    try:
        if fmt == 'pdf':
            if not data.startswith(b'%PDF-'):
                raise ValueError('signature')
        elif fmt == 'docx':
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > MAX_TEXT * 2:
                    raise ValueError('expanded archive limit')
                if any(e.flag_bits & 1 for e in entries) or 'word/document.xml' not in archive.namelist():
                    raise ValueError('invalid DOCX')
                if any('vbaproject' in e.filename.lower() for e in entries):
                    raise ValueError('macros')
        elif fmt == 'png':
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('signature')
        elif fmt in {'jpg', 'jpeg'}:
            if not data.startswith(b'\xff\xd8\xff'):
                raise ValueError('signature')
        else:
            text = data.decode('utf-8-sig')
            if '\x00' in text or '<html' in text.lower() or '<script' in text.lower():
                raise ValueError('unsupported text')
    except (ValueError, UnicodeError, zipfile.BadZipFile) as exc:
        raise ValidationError('File content does not match a supported safe document format.') from exc
    return name, fmt, hashlib.sha256(data).hexdigest()


def _ocr(path):
    """No network egress. Tesseract must be installed in the isolated worker."""
    result = subprocess.run(
        ['tesseract', str(path), 'stdout'], capture_output=True, timeout=15, check=True,
    )
    if len(result.stdout) > MAX_TEXT:
        raise ValueError('TEXT_LIMIT_EXCEEDED')
    return result.stdout.decode('utf-8')


def extract_sections(version):
    path = Path(version.original.path)
    fmt = version.detected_format
    if fmt in {'txt', 'md'}:
        sections = [('Document', path.read_text(encoding='utf-8-sig'))]
    elif fmt == 'docx':
        from docx import Document
        doc = Document(path)
        text = '\n'.join([p.text for p in doc.paragraphs] + [
            ' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows
        ])
        sections = [('Document', text)]
    elif fmt == 'pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError('ENCRYPTED_PDF')
        if len(reader.pages) > MAX_PAGES:
            raise ValueError('PAGE_LIMIT_EXCEEDED')
        sections = []
        with tempfile.TemporaryDirectory(prefix='library-ocr-') as directory:
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if not text.strip():
                    prefix = str(Path(directory) / f'page-{index}')
                    subprocess.run([
                        'pdftoppm', '-f', str(index), '-l', str(index), '-scale-to', '2000',
                        '-singlefile', '-png', str(path), prefix,
                    ], capture_output=True, timeout=15, check=True)
                    text = _ocr(prefix + '.png')
                sections.append((f'Page {index}', text))
    else:
        sections = [('Scan', _ocr(path))]
    if sum(len(text.encode('utf-8')) for _, text in sections) > MAX_TEXT:
        raise ValueError('TEXT_LIMIT_EXCEEDED')
    if not any(text.strip() for _, text in sections):
        raise ValueError('NO_EXTRACTABLE_TEXT')
    return sections


def chunk_sections(sections):
    chunks = []
    for section, text in sections:
        text = text.replace('\x00', '').strip()
        for start in range(0, len(text), 1800):
            part = text[start:start + 2000]
            if part.strip():
                chunks.append((section, part, hashlib.sha256(part.encode()).hexdigest()))
            if len(chunks) > MAX_CHUNKS:
                raise ValueError('CHUNK_LIMIT_EXCEEDED')
    return chunks
