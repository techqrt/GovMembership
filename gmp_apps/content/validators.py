from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

from gmp.config import Configurations
from gmp_apps.common.media import ALLOWED_TYPES_TEXT, sniff_image_extension
from gmp_apps.common.url_safety import validate_public_url


def validate_video_url(value: str) -> None:
    """Videos are links to an allow-listed video host (YouTube and Vimeo by default), over https.
    We never store or stream video files ourselves."""
    validate_public_url(value)
    parts = urlsplit(value)
    if parts.scheme != 'https':
        raise ValidationError('Video links must use https')
    host = (parts.hostname or '').lower()
    allowed = [h.strip().lower() for h in Configurations.content_video_hosts if h.strip()]
    if not any(host == h or host.endswith('.' + h) for h in allowed):
        raise ValidationError(f'Video host not allowed. Allowed: {", ".join(allowed)}')


def validate_cover_upload(file) -> None:  # noqa: ANN001
    """Admin upload check for cover pictures: size cap and a real image signature (no SVG)."""
    if file.size > Configurations.content_image_max_bytes:
        raise ValidationError(f'Image is larger than {Configurations.content_image_max_bytes // 1_000_000} MB')
    head = file.read(16)
    file.seek(0)
    if sniff_image_extension(head) is None:
        raise ValidationError(f'Upload a {ALLOWED_TYPES_TEXT} image')
