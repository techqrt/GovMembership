import dataclasses
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_SITEMAP_BYTES = 5_000_000
MAX_SITEMAP_URLS = 20_000
SITEMAP_NS = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
# One path segment of lowercase letters, digits, hyphens: scheme pages. Language, webstory and node
# paths have more segments and are not schemes.
SCHEME_PATH = re.compile(r'^/[a-z0-9][a-z0-9_\-]{1,200}$')


class SitemapError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class SitemapEntry:
    url: str
    lastmod: datetime | None


def normalize_url(url: str) -> str:
    """Canonical source URL: https, lowercase host, no query/fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip('/') or '/'
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}{path}'


def parse_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace('Z', '+00:00')
    for candidate in (text, text + ':00', text + 'T00:00+00:00'):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def parse_sitemap(xml_bytes: bytes) -> list[SitemapEntry]:
    """Parse a sitemap defensively: size cap, and any DTD/entity declaration is refused, which
    removes entity-expansion attacks without needing an extra XML library."""
    if len(xml_bytes) > MAX_SITEMAP_BYTES:
        raise SitemapError('Sitemap is too large')
    head = xml_bytes[:2000].lower()
    if b'<!doctype' in head or b'<!entity' in xml_bytes.lower():
        raise SitemapError('Sitemap contains a DTD or entity declaration')
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise SitemapError(f'Sitemap is not valid XML: {error}') from error
    if root.tag != f'{SITEMAP_NS}urlset':
        raise SitemapError('Not a urlset sitemap (sitemap indexes are not supported)')
    entries: list[SitemapEntry] = []
    for node in root.findall(f'{SITEMAP_NS}url'):
        loc = node.find(f'{SITEMAP_NS}loc')
        if loc is None or not (loc.text or '').strip():
            continue
        lastmod = node.find(f'{SITEMAP_NS}lastmod')
        entries.append(SitemapEntry(normalize_url(loc.text), parse_lastmod(lastmod.text if lastmod is not None else None)))
        if len(entries) > MAX_SITEMAP_URLS:
            raise SitemapError('Sitemap has too many URLs')
    return entries


def is_scheme_url(url: str, allowed_host: str) -> bool:
    """Only https URLs on the single approved host, one clean path segment, no port or credentials."""
    parts = urlsplit(url)
    return (
        parts.scheme == 'https'
        and parts.netloc == allowed_host
        and not parts.query
        and bool(SCHEME_PATH.match(parts.path))
    )
