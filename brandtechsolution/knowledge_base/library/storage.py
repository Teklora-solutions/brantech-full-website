"""Private originals: never use the public default media storage."""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class LibraryStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(file_permissions_mode=0o600, directory_permissions_mode=0o700)

    @property
    def location(self):
        root = Path(settings.LIBRARY_STORAGE_ROOT).resolve()
        for public in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
            if public and root.is_relative_to(Path(public).resolve()):
                raise ImproperlyConfigured('Library storage must be outside public media/static roots.')
        return str(root)

    def url(self, name):
        raise ValueError('Library originals have no public URL.')


def version_path(instance, filename):
    return f'originals/{uuid4().hex}'


library_storage = LibraryStorage()
