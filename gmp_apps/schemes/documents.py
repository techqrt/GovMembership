from django.core.exceptions import ValidationError

from gmp.config import Configurations

MAX_DOCUMENTS = 10


def looks_like_pdf(head: bytes) -> bool:
    """A PDF starts with '%PDF-'. Checked on the bytes, never on a file name, URL or Content-Type."""
    return head.startswith(b'%PDF-')


def validate_pdf_upload(file) -> None:  # noqa: ANN001
    """Admin upload check: size cap and a real PDF signature."""
    if file.size > Configurations.scheme_document_max_bytes:
        raise ValidationError(f'Document is larger than {Configurations.scheme_document_max_bytes // 1_000_000} MB')
    head = file.read(8)
    file.seek(0)
    if not looks_like_pdf(head):
        raise ValidationError('Upload a PDF document')
