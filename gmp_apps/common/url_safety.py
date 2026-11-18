import ipaddress
import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

from gmp.config import Configurations

CONTROL_OR_SPACE = re.compile(r'[\s\x00-\x1f\x7f]')


def validate_public_url(value: str) -> None:
    """Members are sent to this address, so it must be a plain public web URL.

    Refused: any scheme but http/https (javascript:, data:, ftp:, file:...), embedded credentials,
    spaces/control characters, hosts without a dot (single-label names) and loopback/private/link-local
    IP addresses. Over-long values are refused too.
    """
    if len(value) > Configurations.portal_url_max_length:
        raise ValidationError(f'URL is longer than {Configurations.portal_url_max_length} characters')
    if CONTROL_OR_SPACE.search(value):
        raise ValidationError('URL must not contain spaces or control characters')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https'):
        raise ValidationError('URL must start with http:// or https://')
    if parts.username is not None or parts.password is not None:
        raise ValidationError('URL must not contain a user name or password')
    host = parts.hostname
    if not host:
        raise ValidationError('URL has no host name')
    try:
        parts.port
    except ValueError:
        raise ValidationError('URL has an invalid port')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or host.endswith('.'):
            raise ValidationError('URL needs a full domain name, for example example.gov.in')
    else:
        if not address.is_global:
            raise ValidationError('URL must not point to a private or local address')


def url_key(value: str) -> str:
    """Canonical form used to stop the same portal being listed twice: lower-case scheme and host,
    no fragment, no trailing slash. The query string is kept (some portals depend on it)."""
    parts = urlsplit(value.strip())
    host = (parts.hostname or '').lower()
    port = f':{parts.port}' if parts.port and parts.port not in (80, 443) else ''
    path = parts.path.rstrip('/')
    query = f'?{parts.query}' if parts.query else ''
    return f'{parts.scheme.lower()}://{host}{port}{path}{query}'
