import logging
import time
from collections.abc import Callable
from urllib.parse import unquote, urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from gmp.config import Configurations
from django.core.files.base import ContentFile

from gmp_apps.schemes.documents import MAX_DOCUMENTS, looks_like_pdf
from gmp_apps.schemes.images import sha256_of, sniff_image_extension
from gmp_apps.schemes.models import Scheme, SchemeDocument, SchemeExclusion, SchemeImage, SchemeSyncRun
from gmp_apps.schemes.models.scheme import SchemeStatus
from gmp_apps.schemes.models.scheme_sync_run import SyncStatus
from gmp_apps.schemes.sync.parser import ParsedScheme, parse_scheme_page
from gmp_apps.schemes.sync.sitemap import SitemapEntry, SitemapError, is_scheme_url, parse_sitemap
from gmp_apps.schemes.sync.source import SchemeSource, SourceError

logger = logging.getLogger(__name__)
MAX_ERROR_LINES = 20
SAVE_EVERY = 25


class SyncBusyError(Exception):
    """Another sync is already running."""


class SchemeSyncRunner:
    """One sync pass over the approved sitemap.

    New URLs are inserted as 'pending_review'; known URLs are fetched only when the sitemap's
    lastmod moved (or `force`), and updated only if the parsed content really changed. The same
    code serves the one-time bulk import (empty database) and the daily Celery Beat run.
    """

    def __init__(
        self,
        source: SchemeSource | None = None,
        trigger: str = 'beat',
        force: bool = False,
        limit: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source or SchemeSource()
        self.trigger = trigger
        self.force = force
        self.limit = limit
        self.sleep = sleep
        self._error_lines: list[str] = []

    def run(self) -> SchemeSyncRun:
        if SchemeSyncRun.is_busy():
            raise SyncBusyError('A scheme sync is already running')
        run = SchemeSyncRun.objects.create(trigger=self.trigger)
        try:
            self._execute(run)
            run.status = SyncStatus.PARTIAL if run.errors else SyncStatus.SUCCESS
        except (SourceError, SitemapError) as error:
            run.status = SyncStatus.FAILED
            self._note(f'Run stopped: {error}')
        except Exception as error:  # noqa: BLE001 - a crashed run must still be closed and recorded
            logger.exception('Scheme sync crashed')
            run.status = SyncStatus.FAILED
            self._note(f'Unexpected error: {type(error).__name__}')
        finally:
            run.error_summary = '\n'.join(self._error_lines)
            run.finished_date_time = timezone.now()
            run.save()
        return run

    # ---------- steps ----------

    def _execute(self, run: SchemeSyncRun) -> None:
        self.source.load_robots()
        entries = parse_sitemap(self.source.fetch_sitemap())
        run.sitemap_urls = len(entries)
        candidates = self._scheme_candidates(entries)
        run.scheme_urls = len(candidates)
        if not candidates:
            raise SitemapError('No scheme URLs found in the sitemap')
        queue = self._build_queue(run, candidates)
        self._process(run, queue)
        self._verify_media(run)

    def _verify_media(self, run: SchemeSyncRun) -> None:
        """Run-level check: how many source schemes still lack verified pictures/PDFs. They are retried
        by the next run automatically; the count is on the run log so it is never silent."""
        run.media_pending = Scheme.objects.filter(
            source_url__isnull=False, is_manual=False, locally_edited=False, media_synced_at__isnull=True,
        ).count()
        if run.media_pending:
            self._note(f'{run.media_pending} scheme(s) still waiting for pictures/PDFs (retried on the next run)')

    @staticmethod
    def _scheme_candidates(entries: list[SitemapEntry]) -> dict[str, SitemapEntry]:
        candidates: dict[str, SitemapEntry] = {}
        for entry in entries:
            if is_scheme_url(entry.url, Configurations.scheme_source_host):
                candidates.setdefault(entry.url, entry)
        return candidates

    def _build_queue(self, run: SchemeSyncRun, candidates: dict[str, SitemapEntry]) -> list[SitemapEntry]:
        excluded = set(SchemeExclusion.objects.values_list('source_url', flat=True))
        known = {
            row['source_url']: row
            for row in Scheme.objects.exclude(source_url=None).values(
                'source_url', 'source_lastmod', 'media_synced_at', 'locally_edited', 'is_manual',
            )
        }
        queue: list[SitemapEntry] = []
        requeued = 0
        for url, entry in candidates.items():
            row = known.get(url)
            # A source-owned scheme whose pictures/PDFs were never fully synced is fetched again even if its
            # page has not changed (this is what heals schemes imported before media existed, or after a failed download).
            needs_media = bool(row) and row['media_synced_at'] is None and not row['locally_edited'] and not row['is_manual']
            if url in excluded:
                run.skipped_excluded += 1
            elif row and not self.force and not needs_media and not self._source_changed(entry, row['source_lastmod']):
                run.unchanged += 1
            elif not self.source.allowed_by_robots(url):
                run.skipped_invalid += 1
                self._note(f'Blocked by robots.txt: {url}')
            else:
                requeued += int(needs_media and not self._source_changed(entry, row['source_lastmod']))
                queue.append(entry)
        if requeued:
            self._note(f'{requeued} scheme(s) re-queued because their pictures/PDFs were never fully synced')
        cap = min(Configurations.scheme_sync_max_pages, self.limit or Configurations.scheme_sync_max_pages)
        return queue[:cap]

    @staticmethod
    def _source_changed(entry: SitemapEntry, stored_lastmod) -> bool:  # noqa: ANN001
        return entry.lastmod is None or stored_lastmod is None or entry.lastmod > stored_lastmod

    def _process(self, run: SchemeSyncRun, queue: list[SitemapEntry]) -> None:
        consecutive_errors = 0
        for index, entry in enumerate(queue):
            if index:
                self.sleep(Configurations.scheme_sync_delay_seconds)
            try:
                html = self.source.fetch_page(entry.url)
                consecutive_errors = 0
            except SourceError as error:
                run.errors += 1
                consecutive_errors += 1
                self._note(f'{entry.url}: {error}')
                if consecutive_errors >= Configurations.scheme_sync_max_consecutive_errors:
                    raise SourceError('Too many consecutive fetch errors, stopping this run') from error
                continue
            run.fetched += 1
            parsed = parse_scheme_page(html, entry.url)
            if parsed is None:
                run.skipped_invalid += 1
                self._note(f'Not a parsable scheme page: {entry.url}')
                continue
            scheme_pk, owns_content = self._store(run, entry, parsed)
            if scheme_pk and owns_content:
                images_ok, image_urls = self._sync_images(run, scheme_pk, parsed.images)
                documents_ok, document_urls = self._sync_documents(run, scheme_pk, parsed.links)
                Scheme.objects.filter(pk=scheme_pk).update(
                    expected_media={'images': image_urls, 'documents': document_urls},
                    media_synced_at=timezone.now() if images_ok and documents_ok else None,
                )
            if index % SAVE_EVERY == 0:
                run.save()

    def _store(self, run: SchemeSyncRun, entry: SitemapEntry, parsed: ParsedScheme) -> tuple[int | None, bool]:
        """Insert or update one scheme. Returns (scheme id, whether the sync owns its content, i.e. no admin edits)."""
        fingerprint = parsed.content_hash()
        now = timezone.now()
        try:
            with transaction.atomic():
                scheme = Scheme.objects.select_for_update().filter(source_url=entry.url).first()
                if scheme is None:
                    created = Scheme.objects.create(
                        source_url=entry.url, status=SchemeStatus.PENDING_REVIEW, content_hash=fingerprint,
                        source_lastmod=entry.lastmod, last_synced_at=now, **self._content(parsed),
                    )
                    created.set_tags(parsed.tags)
                    run.created += 1
                    return created.pk, True
                scheme.source_lastmod, scheme.last_synced_at = entry.lastmod, now
                if fingerprint == scheme.content_hash:
                    run.unchanged += 1
                elif scheme.locally_edited or scheme.is_manual:
                    run.skipped_edited += 1  # admin-owned content is never overwritten by the sync
                else:
                    for field, value in self._content(parsed).items():
                        setattr(scheme, field, value)
                    scheme.content_hash = fingerprint
                    scheme.set_tags(parsed.tags)
                    run.updated += 1
                scheme.save()
                return scheme.pk, not (scheme.locally_edited or scheme.is_manual)
        except IntegrityError:
            run.unchanged += 1  # lost a race with another writer on the same URL: nothing to do
            return None, False

    def _sync_images(self, run: SchemeSyncRun, scheme_pk: int, wanted_urls: list[str]) -> tuple[bool, list[str]]:
        """Make the scheme's stored pictures match the page: download missing ones into our own media
        storage, drop ones the page no longer shows. Pictures an admin uploaded (no source URL) are
        never touched. A failed download never fails the scheme: it is reported as not-ok so the scheme
        stays unverified and is retried. Returns (ok, URLs this run is responsible for)."""
        scheme = Scheme.objects.get(pk=scheme_pk)
        existing = {image.source_url: image for image in scheme.images.exclude(source_url=None)}
        for url, image in existing.items():
            if url not in wanted_urls:
                image.delete()
        failed = False
        blocked: list[str] = []
        for position, url in enumerate(wanted_urls):
            if url in existing:
                SchemeImage.objects.filter(pk=existing[url].pk).update(position=position)
                continue
            if not self.source.allowed_by_robots(url):
                self._note(f'Image blocked by robots.txt: {url}')
                blocked.append(url)
                continue
            self.sleep(Configurations.scheme_sync_delay_seconds)
            try:
                data = self.source.fetch_image(url)
            except SourceError as error:
                failed = True
                run.errors += 1
                self._note(f'Image {url}: {error}')
                continue
            if sniff_image_extension(data[:16]) is None:
                failed = True
                run.errors += 1
                self._note(f'Image {url}: not a JPEG/PNG/GIF/WebP file')
                continue
            if scheme.images.filter(sha256=sha256_of(data)).exists():
                continue  # the same picture is already attached (two URLs, one image)
            SchemeImage.objects.create(scheme=scheme, file=ContentFile(data, name='download'), position=position, source_url=url)
            run.images_downloaded += 1
        return not failed, [url for url in wanted_urls if url not in blocked]

    @staticmethod
    def _document_candidates(links: list[dict[str, str]]) -> list[dict[str, str]]:
        """PDFs hosted on the source itself (brochures, guidelines), one per file path, in page order.
        The same file is often linked twice under different spellings of its URL."""
        host = Configurations.scheme_source_host
        seen: set[str] = set()
        candidates: list[dict[str, str]] = []
        for link in links:
            parts = urlsplit(link.get('url', ''))
            if parts.netloc.lower() != host or not parts.path.startswith('/sites/default/files/') or not parts.path.lower().endswith('.pdf'):
                continue
            key = unquote(parts.path).lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                'url': link['url'], 'label': link.get('label', '')[:200],
                'kind': 'brochure' if link.get('kind') == 'brochure' else 'document',
            })
            if len(candidates) >= MAX_DOCUMENTS:
                break
        return candidates

    def _sync_documents(self, run: SchemeSyncRun, scheme_pk: int, links: list[dict[str, str]]) -> tuple[bool, list[str]]:
        """Mirror the source's PDFs into our own storage (same rules as pictures): download missing
        ones, drop ones the page no longer links, never touch documents an admin uploaded, never fail
        the scheme because of a bad download (it is marked for a retry instead)."""
        wanted = self._document_candidates(links)
        wanted_urls = [item['url'] for item in wanted]
        scheme = Scheme.objects.get(pk=scheme_pk)
        existing = {doc.source_url: doc for doc in scheme.documents.exclude(source_url=None)}
        for url, document in existing.items():
            if url not in wanted_urls:
                document.delete()
        failed = False
        blocked: list[str] = []
        for position, item in enumerate(wanted):
            url = item['url']
            if url in existing:
                SchemeDocument.objects.filter(pk=existing[url].pk).update(position=position, label=item['label'], kind=item['kind'])
                continue
            if not self.source.allowed_by_robots(url):
                self._note(f'Document blocked by robots.txt: {url}')
                blocked.append(url)
                continue
            self.sleep(Configurations.scheme_sync_delay_seconds)
            try:
                data = self.source.fetch_document(url)
            except SourceError as error:
                failed = True
                run.errors += 1
                self._note(f'Document {url}: {error}')
                continue
            if not looks_like_pdf(data[:8]):
                failed = True
                run.errors += 1
                self._note(f'Document {url}: not a PDF file')
                continue
            if scheme.documents.filter(sha256=sha256_of(data)).exists():
                continue  # the same file is already attached under another URL
            SchemeDocument.objects.create(
                scheme=scheme, file=ContentFile(data, name='download'), label=item['label'], kind=item['kind'],
                position=position, source_url=url,
            )
            run.documents_downloaded += 1
        return not failed, [url for url in wanted_urls if url not in blocked]

    @staticmethod
    def _content(parsed: ParsedScheme) -> dict[str, object]:
        return {
            'title': parsed.title,
            'description': parsed.description,
            'eligibility': parsed.eligibility,
            'benefits': parsed.benefits,
            'application_procedure': parsed.application_procedure,
            'required_documents': parsed.required_documents,
            'department': parsed.department,
            'highlights': parsed.highlights,
            'contact_details': parsed.contact_details,
            'links': parsed.links,
            'overview': parsed.overview,
            'additional_sections': parsed.additional_sections,
        }

    def _note(self, line: str) -> None:
        if len(self._error_lines) < MAX_ERROR_LINES:
            self._error_lines.append(line)
