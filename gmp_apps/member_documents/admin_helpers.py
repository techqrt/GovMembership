from collections.abc import Iterable

from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

from gmp_apps.member_documents.models import MemberDocument

DOWNLOAD_PERMISSION = 'member_documents.download_memberdocument'


def document_links(documents: Iterable[MemberDocument], can_download: bool, empty: str = 'None attached') -> str | SafeString:
    """Admin read-only listing of a member's attached files. The Download link appears only for staff who hold the
    document download permission (the download itself enforces it and logs it); others see the names."""
    items = list(documents)
    if not items:
        return empty
    rows = (
        (
            document.get_document_type_display(), document.download_name,
            format_html('<a href="{}">Download</a>', reverse('admin:member_documents_memberdocument_download', args=[document.pk]))
            if can_download else '(no download permission)',
        )
        for document in items
    )
    return format_html_join(mark_safe('<br>'), '{}: {} {}', rows)
