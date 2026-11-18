import hashlib

ALLOWED_TYPES_TEXT = 'JPEG, PNG, GIF or WebP'


def sniff_image_extension(data: bytes) -> str | None:
    """File type from the first bytes, never from a file name or Content-Type header.

    SVG and HTML are deliberately not accepted: they can carry script.
    """
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
