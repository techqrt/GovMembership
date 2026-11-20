import re

from django.http import FileResponse

MAX_NAME_LENGTH = 120

# Anything a browser, server or operating system could run or interpret. Checked against EVERY dot
# separated part of the name, so `invoice.php.jpg` is refused as well.
DENIED_EXTENSIONS = frozenset({
    'html', 'htm', 'xhtml', 'shtml', 'svg', 'svgz', 'xml', 'xsl', 'xslt', 'mht', 'mhtml', 'hta', 'swf',
    'js', 'mjs', 'cjs', 'jsx', 'ts', 'vbs', 'vbe', 'jse', 'wsf', 'wsh', 'ps1', 'psm1', 'psd1',
    'sh', 'bash', 'zsh', 'csh', 'ksh', 'bat', 'cmd', 'com', 'exe', 'dll', 'msi', 'scr', 'cpl', 'pif', 'lnk', 'reg', 'sys',
    'jar', 'war', 'apk', 'app', 'dmg', 'pkg', 'deb', 'rpm', 'bin', 'elf', 'so', 'dylib', 'class',
    'php', 'php3', 'php4', 'php5', 'php7', 'phtml', 'phar', 'pl', 'py', 'pyc', 'rb', 'cgi', 'asp', 'aspx', 'jsp', 'jspx', 'cfm', 'htaccess',
})
EXECUTABLE_MAGIC = (b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')
MARKUP_STARTS = (b'<!doctype', b'<html', b'<head', b'<body', b'<svg', b'<?xml', b'<?php', b'<script', b'<iframe', b'<%', b'<?')
MARKUP_ANYWHERE = (b'<script', b'<html', b'<svg', b'<iframe', b'<?php', b'<!doctype html')
SCAN_BYTES = 2048
SAFE_NAME = re.compile(r'[^A-Za-z0-9._ -]')


def sniff_type(data: bytes) -> tuple[str, str]:
    """(extension, content type) from the first bytes. Unknown content is a plain binary blob.
    The client's file name and Content-Type header are never trusted."""
    if data.startswith(b'%PDF-'):
        return 'pdf', 'application/pdf'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg', 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png', 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif', 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp', 'image/webp'
    return 'dat', 'application/octet-stream'


def is_image(content_type: str) -> bool:
    return content_type.startswith('image/')


def has_denied_extension(name: str) -> bool:
    parts = [part.lower() for part in name.replace('\\', '/').rsplit('/', 1)[-1].split('.')[1:]]
    return any(part.strip() in DENIED_EXTENSIONS for part in parts)


def _text_start(data: bytes) -> bytes:
    """First bytes as lower-case text for markup checks, undoing a UTF-16 byte order mark."""
    head = data[:SCAN_BYTES]
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        head = head.decode('utf-16', errors='ignore').encode('utf-8', errors='ignore')
    return head.lstrip(b'\xef\xbb\xbf \t\r\n\x00').lower()


def has_dangerous_content(data: bytes) -> bool:
    """Executables, scripts and markup that a browser could run, found by their bytes."""
    if data.startswith(EXECUTABLE_MAGIC):
        return True
    text = _text_start(data)
    if text.startswith(b'#!') or text.startswith(MARKUP_STARTS):
        return True
    extension, _ = sniff_type(data)
    if extension != 'dat':
        return False  # a real PDF or picture: the signature is checked, the rest is just data
    return any(marker in text for marker in MARKUP_ANYWHERE)


def display_name(original: str, extension: str) -> str:
    """A harmless download name: letters, digits and . _ - only, no path, never starting with a dot."""
    base = original.replace('\\', '/').rsplit('/', 1)[-1]
    stem = SAFE_NAME.sub('_', base.rsplit('.', 1)[0] if '.' in base else base).strip(' ._-')[:MAX_NAME_LENGTH - 8]
    return f'{stem or "document"}.{extension}'


def attachment_response(path_or_file, filename: str) -> FileResponse:  # noqa: ANN001
    """Serve a stored file so a browser can only save it: octet-stream attachment, no sniffing,
    nothing may run or embed it, never cached."""
    response = FileResponse(path_or_file, as_attachment=True, filename=filename, content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['Cache-Control'] = 'private, no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response
