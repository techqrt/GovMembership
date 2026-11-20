from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Local disk storage for files that must never have a public URL (identity documents).

    The folder is outside MEDIA_ROOT, and `url()` is disabled on purpose: the only way to read a
    file is a view that checks who is asking.
    """

    def __init__(self) -> None:
        super().__init__(location=str(settings.PRIVATE_MEDIA_ROOT), base_url=None)

    def url(self, name: str | None) -> str:
        raise ValueError('Private files have no public URL')


def private_storage() -> PrivateStorage:
    """Callable for FileField(storage=...): resolved at runtime so tests can point it elsewhere."""
    return PrivateStorage()
