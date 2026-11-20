import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit
from urllib.robotparser import RobotFileParser

from gmp.config import Configurations

USER_AGENT = 'GovtMembershipSchemeSync/1.0'
MAX_SITEMAP_BYTES = 5_000_000
MAX_PAGE_BYTES = 3_000_000
MAX_ROBOTS_BYTES = 200_000
RETRIES = 2


class SourceError(Exception):
    """Fetching from the approved source failed (network, status, size, or an off-host redirect)."""

    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable  # only transient failures (network, 5xx) are worth retrying


def is_allowed_url(url: str, host: str | None = None) -> bool:
    """Only https on the single approved host, default port, no credentials."""
    parts = urlsplit(url)
    return (
        parts.scheme == 'https'
        and parts.netloc == (host or Configurations.scheme_source_host)
        and parts.username is None
        and parts.port is None
    )


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _ascii_url(url: str) -> str:
    """Percent-encode non-ASCII characters (e.g. Hindi file names): HTTP request lines must be ASCII.
    Already-encoded sequences and URL punctuation are left untouched."""
    return quote(url, safe="%:/?#[]@!$&'()*+,;=~-._")


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect that leaves the approved host is refused, so the source cannot steer us elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not is_allowed_url(newurl):
            raise SourceError(f'Refusing redirect to {urlsplit(newurl).netloc or "unknown host"}', status=code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SchemeSource:
    """The only network door of the scheme sync. Host-locked, size-capped, time-boxed."""

    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        self._opener = opener or urllib.request.build_opener(_SameHostRedirects(), urllib.request.HTTPSHandler(context=_ssl_context()))
        self._robots: RobotFileParser | None = None

    @property
    def sitemap_url(self) -> str:
        return f'https://{Configurations.scheme_source_host}/sitemap.xml'

    def fetch(self, url: str, max_bytes: int) -> bytes:
        if not is_allowed_url(url):
            raise SourceError(f'URL is not on the approved source: {urlsplit(url).netloc}')
        last_error: SourceError | None = None
        for attempt in range(RETRIES + 1):
            try:
                return self._get(url, max_bytes)
            except SourceError as error:
                last_error = error
                if not error.retryable or attempt == RETRIES:
                    break
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _get(self, url: str, max_bytes: int) -> bytes:
        request = urllib.request.Request(_ascii_url(url), headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xml;q=0.9,*/*;q=0.5'})
        try:
            with self._opener.open(request, timeout=Configurations.scheme_sync_request_timeout) as response:
                if response.status != 200:
                    raise SourceError(f'Unexpected status {response.status}', status=response.status, retryable=response.status >= 500)
                data = response.read(max_bytes + 1)
        except urllib.error.HTTPError as error:
            raise SourceError(f'HTTP {error.code}', status=error.code, retryable=error.code >= 500 or error.code == 429) from error
        except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError) as error:
            raise SourceError(f'Network error: {error}', retryable=True) from error
        except UnicodeError as error:
            raise SourceError(f'URL cannot be requested: {error.__class__.__name__}') from error
        if len(data) > max_bytes:
            raise SourceError('Response is too large')
        return data

    def fetch_sitemap(self) -> bytes:
        return self.fetch(self.sitemap_url, MAX_SITEMAP_BYTES)

    def fetch_image(self, url: str) -> bytes:
        """Raw bytes of a scheme picture. Host-locked like everything else, and only the source's
        upload folder; the caller checks that the bytes really are an image."""
        if not urlsplit(url).path.startswith('/sites/default/files/'):
            raise SourceError('Not an upload path on the approved source')
        return self.fetch(url, Configurations.scheme_image_max_bytes)

    def fetch_document(self, url: str) -> bytes:
        """Raw bytes of a source-hosted PDF. Host-locked, upload folder only, '.pdf' only, size-capped;
        the caller checks that the bytes really are a PDF."""
        path = urlsplit(url).path
        if not path.startswith('/sites/default/files/') or not path.lower().endswith('.pdf'):
            raise SourceError('Not a PDF in the upload folder of the approved source')
        return self.fetch(url, Configurations.scheme_document_max_bytes)

    def fetch_page(self, url: str) -> str:
        return self.fetch(url, MAX_PAGE_BYTES).decode('utf-8', errors='replace')

    def load_robots(self) -> None:
        """robots.txt is honoured. A missing file (404) means everything is allowed; any other failure aborts."""
        parser = RobotFileParser()
        try:
            raw = self.fetch(f'https://{Configurations.scheme_source_host}/robots.txt', MAX_ROBOTS_BYTES)
            parser.parse(raw.decode('utf-8', errors='replace').splitlines())
        except SourceError as error:
            if error.status != 404:
                raise
            parser.parse([])
        self._robots = parser

    def allowed_by_robots(self, url: str) -> bool:
        return True if self._robots is None else self._robots.can_fetch(USER_AGENT, url)
