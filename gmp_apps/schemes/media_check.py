from collections import defaultdict
from urllib.parse import urlsplit

from django.core.files.storage import default_storage

from gmp_apps.schemes.models import Scheme, SchemeDocument, SchemeImage

def short(url: str) -> str:
    return urlsplit(url).path.rsplit('/', 1)[-1][:60] or url[:60]


def find_problems() -> dict[int, list[str]]:
    """Why a scheme's pictures/PDFs cannot be trusted. Read-only, no network.

    For schemes the sync owns: media sync never completed, a picture or PDF the page promised is not
    stored. For every scheme: a stored picture/PDF whose file is missing from storage.
    """
    problems: dict[int, list[str]] = defaultdict(list)
    owned = Scheme.objects.filter(source_url__isnull=False, is_manual=False, locally_edited=False).prefetch_related('images', 'documents')
    for scheme in owned:
        if scheme.media_synced_at is None:
            problems[scheme.pk].append('pictures/PDFs never fully synced')
        expected = scheme.expected_media or {}
        stored_images = {image.source_url for image in scheme.images.all()}
        stored_documents = {document.source_url for document in scheme.documents.all()}
        problems[scheme.pk] += [f'picture not stored: {short(u)}' for u in expected.get('images', []) if u not in stored_images]
        problems[scheme.pk] += [f'PDF not stored: {short(u)}' for u in expected.get('documents', []) if u not in stored_documents]
    for model, label in ((SchemeImage, 'picture'), (SchemeDocument, 'PDF')):
        for row in model.objects.only('scheme_id', 'file').iterator():
            if not default_storage.exists(row.file.name):
                problems[row.scheme_id].append(f'{label} file missing from storage: {row.file.name}')
    return {scheme_id: reasons for scheme_id, reasons in problems.items() if reasons}


def requeue_media(problems: dict[int, list[str]]) -> tuple[set[int], int]:
    """Offline half of a repair: drop picture/PDF records whose file is gone and mark the schemes
    the sync owns as waiting, so the next sync downloads them again. Returns (owned scheme ids,
    removed record count). Schemes owned by an admin (edited or manual) are left alone."""
    owned = set(Scheme.objects.filter(
        pk__in=list(problems), source_url__isnull=False, is_manual=False, locally_edited=False,
    ).values_list('pk', flat=True))
    removed = 0
    for model in (SchemeImage, SchemeDocument):
        for row in model.objects.only('scheme_id', 'file', 'source_url').iterator():
            if row.scheme_id in owned and row.source_url and not default_storage.exists(row.file.name):
                row.delete()  # the sync downloads it again
                removed += 1
    Scheme.objects.filter(pk__in=owned).update(media_synced_at=None)
    return owned, removed
