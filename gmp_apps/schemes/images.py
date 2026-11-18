from django.core.exceptions import ValidationError

from gmp.config import Configurations
from gmp_apps.common.media import ALLOWED_TYPES_TEXT, sha256_of, sniff_image_extension

__all__ = ['ALLOWED_TYPES_TEXT', 'sha256_of', 'sniff_image_extension', 'validate_image_upload']


def validate_image_upload(file) -> None:  # noqa: ANN001
    """Admin upload check: size cap and a real image signature."""
    if file.size > Configurations.scheme_image_max_bytes:
        raise ValidationError(f'Image is larger than {Configurations.scheme_image_max_bytes // 1_000_000} MB')
    head = file.read(16)
    file.seek(0)
    if sniff_image_extension(head) is None:
        raise ValidationError(f'Upload a {ALLOWED_TYPES_TEXT} image')
