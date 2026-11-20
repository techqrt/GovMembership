import atexit
import shutil
import tempfile
import urllib.error
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.conf import settings as django_settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from gmp.config import Configurations
from gmp_apps.authentication.models import User
from gmp_apps.schemes.documents import looks_like_pdf
from gmp_apps.schemes.images import sniff_image_extension
from gmp_apps.schemes.models import Scheme, SchemeDocument, SchemeExclusion, SchemeImage, SchemeSyncRun
from gmp_apps.schemes.sync import source as source_module
from gmp_apps.schemes.sync.dom import parse_html
from gmp_apps.schemes.sync.parser import parse_scheme_page
from gmp_apps.schemes.sync.runner import SchemeSyncRunner, SyncBusyError
from gmp_apps.schemes.sync.sitemap import (
    SitemapError, is_scheme_url, normalize_url, parse_lastmod, parse_sitemap,
)
from gmp_apps.schemes.sync.source import SchemeSource, SourceError, is_allowed_url
from gmp_apps.schemes.tasks import sync_schemes

HOST = 'https://www.govtschemes.in'
PASSWORD = 'Sunrise#Valley42'
FAST_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Downloaded and uploaded pictures go to a throwaway folder, never to the real MEDIA_ROOT.
MEDIA_TMP = tempfile.mkdtemp(prefix='gmp-test-media-')
atexit.register(shutil.rmtree, MEDIA_TMP, ignore_errors=True)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 40
JPG = b'\xff\xd8\xff\xe0' + b'0' * 40
GIF = b'GIF89a' + b'0' * 40
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'0' * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML_BYTES = b'<html><script>alert(1)</script></html>'
PDF = b'%PDF-1.4\n' + b'0' * 40


def png(tag: str = '') -> bytes:
    """A tiny PNG-signature file, unique per tag (distinct content, distinct hash)."""
    return PNG + tag.encode()


def pdf(tag: str = '') -> bytes:
    """A tiny PDF-signature file, unique per tag."""
    return PDF + tag.encode()


def clean_media() -> None:
    shutil.rmtree(Path(MEDIA_TMP) / 'schemes', ignore_errors=True)


def url(slug: str) -> str:
    return f'{HOST}/{slug}'


def page(
    title: str = 'Sample Scheme',
    intro: str = 'A scheme that helps farmers.',
    benefits: tuple[str, ...] = ('Rs. 5000 per year', 'Free insurance'),
    eligibility: tuple[str, ...] = ('Must be a resident', 'Age above 18'),
    documents: tuple[str, ...] = ('Aadhaar card', 'Bank passbook'),
    how: tuple[str, ...] = ('Visit the portal', 'Fill the form'),
    table: tuple[tuple[str, str], ...] = (('Ministry', 'Ministry of Agriculture'),),
    images: tuple[str, ...] = ('/sites/default/files/2024-01/main-image.jpg',),
    highlights: str = '',
    headings: dict[str, str] | None = None,
    links: tuple[tuple[str, str], ...] = (('Portal LINKTEXT', 'https://portal.example/apply'),),
    contact: tuple[str, ...] = ('Helpline CONTACTTEXT',),
    extra: tuple[tuple[str, tuple[str, ...]], ...] = (),
    tags: tuple[tuple[str, str], ...] = (),
    website: tuple[str, str] | None = None,
    brochure: tuple[str, str] | None = None,
    ministry: str = '',
    preamble: str = '',
) -> str:
    """Drupal-like page modelled on the real source markup, plus the noise that must never be imported."""
    names = {'intro': 'Introduction:-', 'benefits': 'Benefits', 'eligibility': 'Eligibility', 'documents': 'Documents Required',
             'how': 'How to Apply'}
    names.update(headings or {})

    def block(key: str, items: tuple[str, ...], ordered: bool = False) -> str:
        if not items:
            return ''
        return f'<h4>{names[key]}</h4><ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'

    rows = ''.join(f'<tr><td><strong>{k}</strong></td><td>{v}</td></tr>' for k, v in table)
    imgs = ''.join(f'<img src="{src}" alt="x">' for src in images)
    extra_html = ''.join(f'<h4>{h}</h4><ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>' for h, items in extra)
    links_html = (
        '<h3>Important Links</h3><ul>' + ''.join(f'<li><a href="{href}">{label}</a></li>' for label, href in links) + '</ul>' if links else ''
    )
    contact_html = '<h3>Contact Details</h3><ul>' + ''.join(f'<li>{c}</li>' for c in contact) + '</ul>' if contact else ''
    group_class = {'scheme_type': 'field-scheme-type', 'person_type': 'field-person-type', 'caste': 'field-caste'}
    tags_html = ''.join(
        f'<div class="field field--name-{group_class[g]}"><div class="taxonomy-term"><a href="/taxonomy/term/1">'
        f'<div class="field field--name-name">{n}</div></a></div></div>' for g, n in tags
    )
    ministry_html = (
        f'<div class="field field--name-field-ministry"><div class="taxonomy-term"><div class="field field--name-name">{ministry}</div></div></div>'
        if ministry else ''
    )
    website_html = (
        f'<div class="field field--name-field-website"><div class="field__label">Website</div><div class="field__item"><a href="{website[1]}">{website[0]}</a></div></div>'
        if website else ''
    )
    brochure_html = (
        f'<div class="field field--name-field-information-brochure"><div class="field__item"><span class="file"><a href="{brochure[1]}">{brochure[0]}</a></span></div></div>'
        if brochure else ''
    )
    preamble_html = f'<p>{preamble}</p>' if preamble else ''
    intro_html = f'<h4>{names["intro"]}</h4><p>{intro}</p>' if intro else ''
    highlights_html = (
        f'<div class="field field--name-field-highlights"><div class="field__label">Highlights</div>'
        f'<div class="field__item"><ul><li>{highlights}</li></ul></div></div>' if highlights else ''
    )
    return f"""<html><head><title>{title} | Govt Schemes India</title></head><body>
<nav><div class="field--name-body"><p>Free Schemes Alerts | Discussion Forum</p></div></nav>
<h1><span class="field field--name-title">{title}</span></h1>
<article data-history-node-id="10">
 <footer class="author-details-wrapper"><img src="/sites/default/files/styles/thumbnail/public/pictures/2022-04/author.jpg"></footer>
 <div class="leader-image"><img src="/sites/default/files/styles/medium/public/2024-10/Leader%20Photo.jpg"></div>
 <div class="addtoany">Share this SHARETEXT</div>
 <div class="clearfix text-formatted field field--name-body field--type-text-with-summary">
  <table><tbody>{rows}</tbody></table>{preamble_html}
  {intro_html}{block('benefits', benefits)}{block('eligibility', eligibility)}{block('documents', documents)}{block('how', how)}{extra_html}
  {links_html}{contact_html}
  {imgs}
 </div>{tags_html}{ministry_html}{website_html}{brochure_html}
 <div class="clearfix field field--name-body"><p>Advertisement ADTEXT</p><script>alert('SCRIPTTEXT')</script></div>
 {highlights_html}
 <div class="field--name-field-scheme-forum"><div class="forum-invitation">Join our forum FORUMTEXT</div></div>
 <section class="comments"><h2>Comments</h2>
  <div class="field field--name-comment-body"><p>SPAMMY COMMENT click http://evil.example</p></div>
  <img src="/sites/default/files/2024-01/commenter-upload.jpg"></section>
</article></body></html>"""


def sitemap(*entries: tuple[str, str | None]) -> bytes:
    body = ''.join(
        f'<url><loc>{u}</loc>' + (f'<lastmod>{m}</lastmod>' if m else '') + '</url>' for u, m in entries
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>').encode()


class FakeSource(SchemeSource):
    """Network-free stand-in for the approved source."""

    def __init__(
        self, sitemap_xml: bytes | Exception, pages: dict[str, str | Exception], blocked: tuple[str, ...] = (),
        images: dict[str, bytes | Exception] | None = None, documents: dict[str, bytes | Exception] | None = None,
    ) -> None:
        super().__init__(opener=object())  # type: ignore[arg-type]
        self.sitemap_xml, self.pages, self.blocked = sitemap_xml, pages, blocked
        self.images = images or {}
        self.documents = documents or {}
        self.fetched: list[str] = []
        self.fetched_images: list[str] = []
        self.fetched_documents: list[str] = []

    def load_robots(self) -> None:
        return None

    def fetch_sitemap(self) -> bytes:
        if isinstance(self.sitemap_xml, Exception):
            raise self.sitemap_xml
        return self.sitemap_xml

    def fetch_page(self, page_url: str) -> str:
        self.fetched.append(page_url)
        value = self.pages[page_url]
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_image(self, image_url: str) -> bytes:
        self.fetched_images.append(image_url)
        value = self.images.get(image_url, png(image_url))  # default: a distinct valid picture per URL
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_document(self, document_url: str) -> bytes:
        self.fetched_documents.append(document_url)
        value = self.documents.get(document_url, pdf(document_url))  # default: a distinct valid PDF per URL
        if isinstance(value, Exception):
            raise value
        return value

    def allowed_by_robots(self, page_url: str) -> bool:
        return page_url not in self.blocked


# ======================================================================== parser

class ParserTests(TestCase):
    def parse(self, html: str, slug: str = 'sample-scheme'):
        return parse_scheme_page(html, url(slug))

    def test_extracts_every_field_as_plain_text(self) -> None:
        scheme = self.parse(page())
        self.assertEqual(scheme.title, 'Sample Scheme')
        self.assertEqual(scheme.description, 'A scheme that helps farmers.')
        self.assertEqual(scheme.benefits, '- Rs. 5000 per year\n- Free insurance')
        self.assertEqual(scheme.eligibility, '- Must be a resident\n- Age above 18')
        self.assertEqual(scheme.required_documents, '- Aadhaar card\n- Bank passbook')
        self.assertEqual(scheme.application_procedure, '- Visit the portal\n- Fill the form')
        self.assertEqual(scheme.department, 'Ministry of Agriculture')
        for value in (scheme.description, scheme.benefits, scheme.eligibility, scheme.required_documents):
            self.assertNotIn('<', value)

    def test_noise_and_user_content_never_imported(self) -> None:
        scheme = self.parse(page())
        everything = ' '.join([scheme.title, scheme.description, scheme.benefits, scheme.eligibility,
                               scheme.required_documents, scheme.application_procedure, scheme.department])
        everything += ' ' + str(scheme.links) + ' ' + str(scheme.additional_sections) + ' ' + scheme.highlights + ' ' + scheme.contact_details
        for leaked in ('SPAMMY', 'evil.example', 'SCRIPTTEXT', 'ADTEXT', 'FORUMTEXT', 'SHARETEXT', 'Free Schemes Alerts'):
            self.assertNotIn(leaked, everything)
        self.assertIn('Portal LINKTEXT', str(scheme.links))
        self.assertIn('CONTACTTEXT', scheme.contact_details)

    def test_images_only_original_uploads_of_the_scheme(self) -> None:
        scheme = self.parse(page(images=(
            '/sites/default/files/2024-01/main-image.jpg', '/sites/default/files/2024-01/main-image.jpg',
            '/sites/default/files/styles/small/public/term-icon/2024-03/Girl.jpg', '/sites/default/files/inline-images/info.png',
            '/themes/custom/heart.svg', '/sites/default/files/2024/file.pdf', 'https://evil.example/x.jpg',
        )))
        self.assertEqual(scheme.images, [
            f'{HOST}/sites/default/files/2024-01/main-image.jpg', f'{HOST}/sites/default/files/inline-images/info.png',
        ])
        self.assertNotIn('commenter-upload', ' '.join(scheme.images))
        self.assertNotIn('Leader', ' '.join(scheme.images))

    def test_image_count_is_capped(self) -> None:
        imgs = tuple(f'/sites/default/files/2024-01/p{i}.jpg' for i in range(12))
        self.assertEqual(len(self.parse(page(images=imgs)).images), 5)

    def test_heading_synonyms(self) -> None:
        scheme = self.parse(page(headings={
            'intro': 'Scheme Introduction: A Brief Overview', 'benefits': 'Scheme Benefits', 'eligibility': 'Eligibility Requirements',
            'documents': 'Required Documents', 'how': 'Steps to Apply',
        }))
        self.assertTrue(scheme.description and scheme.benefits and scheme.eligibility and scheme.required_documents and scheme.application_procedure)

    def test_highlights_and_table_fallbacks(self) -> None:
        scheme = self.parse(page(
            intro='', benefits=(), eligibility=(), documents=(), how=(), highlights='Rs.5000 for girls',
            table=(('Ministry', 'Ministry of Minority Affairs'), ('Who can eligible', 'Only girl students'), ('Mode Of Applying', 'Online mode only')),
        ))
        self.assertEqual(scheme.description, 'Rs.5000 for girls'.join(['- ', '']))
        self.assertEqual(scheme.benefits, scheme.description)
        self.assertEqual(scheme.eligibility, 'Only girl students')
        self.assertEqual(scheme.application_procedure, 'Online mode only')

    def test_unknown_department_is_blank(self) -> None:
        self.assertEqual(self.parse(page(table=(('Nodal Department:', 'Not Known Yet.'),))).department, '')
        self.assertEqual(self.parse(page(table=(('Nodal Department:', 'Dept of Health'),))).department, 'Dept of Health')

    def test_not_a_scheme_page_returns_none(self) -> None:
        self.assertIsNone(self.parse('<html><body><h1>About us</h1><p>We are a site</p></body></html>'))
        self.assertIsNone(self.parse(''))
        self.assertIsNone(self.parse('<article data-history-node-id="1"><h1>X</h1></article>'))
        no_title = page().replace('<h1><span class="field field--name-title">Sample Scheme</span></h1>', '').replace('<title>Sample Scheme | Govt Schemes India</title>', '')
        self.assertIsNone(self.parse(no_title))

    def test_markup_in_content_is_stripped_to_text(self) -> None:
        scheme = self.parse(page(intro='Hello <img src=x onerror=alert(1)> <b>bold</b> world'))
        self.assertEqual(scheme.description, 'Hello bold world')
        self.assertNotIn('onerror', scheme.description)

    def test_content_hash_is_stable_and_sensitive(self) -> None:
        first, again, changed = self.parse(page()), self.parse(page()), self.parse(page(benefits=('Different',)))
        self.assertEqual(first.content_hash(), again.content_hash())
        self.assertNotEqual(first.content_hash(), changed.content_hash())

    def test_hostile_input_does_not_crash_or_hang(self) -> None:
        deep = '<div>' * 20000 + 'x' + '</div>' * 20000
        self.assertIsNotNone(parse_html(deep))
        self.assertIsNone(self.parse(deep))
        self.assertIsNone(self.parse('<article data-history-node-id="1"' + '<' * 5000))

    def test_long_fields_are_clipped(self) -> None:
        scheme = self.parse(page(benefits=tuple(f'Benefit line {i} ' + 'x' * 50 for i in range(2000))))
        self.assertLessEqual(len(scheme.benefits), 20000)


# ======================================================================== sitemap

class SitemapTests(TestCase):
    def test_parses_entries_and_lastmod(self) -> None:
        entries = parse_sitemap(sitemap((url('a-scheme'), '2024-05-02T07:44Z'), (url('b-scheme/'), None)))
        self.assertEqual([e.url for e in entries], [url('a-scheme'), url('b-scheme')])
        self.assertEqual(entries[0].lastmod, datetime(2024, 5, 2, 7, 44, tzinfo=dt_timezone.utc))
        self.assertIsNone(entries[1].lastmod)

    def test_lastmod_variants_and_garbage(self) -> None:
        self.assertEqual(parse_lastmod('2024-05-02'), datetime(2024, 5, 2, tzinfo=dt_timezone.utc))
        self.assertEqual(parse_lastmod('2024-05-02T07:44:10+00:00').year, 2024)
        self.assertIsNone(parse_lastmod('not a date'))
        self.assertIsNone(parse_lastmod(None))

    def test_normalize_url(self) -> None:
        self.assertEqual(normalize_url('HTTPS://WWW.GovtSchemes.in/Some-Scheme/?utm=1#frag'), 'https://www.govtschemes.in/Some-Scheme')
        self.assertEqual(normalize_url('https://www.govtschemes.in/'), 'https://www.govtschemes.in/')

    def test_refuses_entity_expansion_and_doctype(self) -> None:
        bomb = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&b;</loc></url></urlset>'
        with self.assertRaises(SitemapError):
            parse_sitemap(bomb)

    def test_refuses_bad_documents(self) -> None:
        for bad in (b'<html></html>', b'not xml', b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>', b'x' * 5_000_001):
            with self.assertRaises(SitemapError):
                parse_sitemap(bad)

    def test_only_clean_scheme_urls_on_the_approved_host(self) -> None:
        host = 'www.govtschemes.in'
        good = ['https://www.govtschemes.in/pm-kisan-samman-nidhi-yojana', 'https://www.govtschemes.in/old-age-pension-scheme']
        bad = [
            'https://www.govtschemes.in/', 'https://www.govtschemes.in/webstory/pm-ujjwala-scheme', 'https://www.govtschemes.in/node/37750',
            'https://www.govtschemes.in/hi/some-scheme', 'http://www.govtschemes.in/some-scheme', 'https://evil.example/some-scheme',
            'https://www.govtschemes.in:8443/some-scheme', 'https://user@www.govtschemes.in/some-scheme', 'https://www.govtschemes.in/some-scheme?x=1',
            'https://www.govtschemes.in.evil.example/some-scheme', 'https://www.govtschemes.in/UPPER', 'https://www.govtschemes.in/a',
        ]
        self.assertTrue(all(is_scheme_url(u, host) for u in good))
        self.assertFalse(any(is_scheme_url(u, host) for u in bad), [u for u in bad if is_scheme_url(u, host)])


# ======================================================================== source (fetch guards)

class _Response:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self.status, self._data = status, data

    def read(self, n: int) -> bytes:
        return self._data[:n]

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Opener:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes, self.calls = list(outcomes), []

    def open(self, request, timeout):  # noqa: ANN001, ANN201
        self.calls.append((request.full_url, request.get_header('User-agent'), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SourceTests(TestCase):
    def setUp(self) -> None:
        sleeper = mock.patch.object(source_module.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_allowed_url_rules(self) -> None:
        self.assertTrue(is_allowed_url(url('x-scheme')))
        for bad in ('http://www.govtschemes.in/x', 'https://evil.example/x', 'https://www.govtschemes.in:444/x', 'https://u:p@www.govtschemes.in/x', 'ftp://www.govtschemes.in/x'):
            self.assertFalse(is_allowed_url(bad), bad)

    def test_off_host_fetch_is_refused_before_any_request(self) -> None:
        opener = _Opener()
        with self.assertRaises(SourceError):
            SchemeSource(opener=opener).fetch('https://evil.example/x', 1000)
        self.assertEqual(opener.calls, [])

    def test_redirect_to_another_host_is_refused(self) -> None:
        handler = source_module._SameHostRedirects()
        with self.assertRaises(SourceError):
            handler.redirect_request(mock.Mock(), None, 302, 'Found', {}, 'https://evil.example/steal')
        with self.assertRaises(SourceError):
            handler.redirect_request(mock.Mock(), None, 302, 'Found', {}, 'http://www.govtschemes.in/downgrade')

    def test_request_is_identified_and_time_boxed(self) -> None:
        opener = _Opener(_Response(b'<html></html>'))
        SchemeSource(opener=opener).fetch_page(url('x-scheme'))
        _, agent, timeout = opener.calls[0]
        self.assertEqual(agent, source_module.USER_AGENT)
        self.assertNotIn('@', agent)
        self.assertEqual(timeout, Configurations.scheme_sync_request_timeout)

    def test_oversized_response_and_bad_status_rejected(self) -> None:
        for response in (_Response(b'x' * 101), _Response(b'ok', status=204)):
            with self.assertRaises(SourceError):
                SchemeSource(opener=_Opener(response)).fetch(url('x-scheme'), 100)

    def test_server_errors_are_retried_then_succeed(self) -> None:
        err = urllib.error.HTTPError(url('x-scheme'), 503, 'busy', {}, None)  # type: ignore[arg-type]
        opener = _Opener(err, err, _Response(b'fine'))
        self.assertEqual(SchemeSource(opener=opener).fetch(url('x-scheme'), 100), b'fine')
        self.assertEqual(len(opener.calls), 3)

    def test_oversized_and_refused_responses_are_never_retried(self) -> None:
        opener = _Opener(_Response(b'x' * 101))
        with self.assertRaises(SourceError):
            SchemeSource(opener=opener).fetch(url('x-scheme'), 100)
        self.assertEqual(len(opener.calls), 1)
        opener = _Opener(_Response(b'ok', status=204))
        with self.assertRaises(SourceError):
            SchemeSource(opener=opener).fetch(url('x-scheme'), 100)
        self.assertEqual(len(opener.calls), 1)

    def test_not_found_is_not_retried(self) -> None:
        opener = _Opener(urllib.error.HTTPError(url('x-scheme'), 404, 'nope', {}, None))  # type: ignore[arg-type]
        with self.assertRaises(SourceError) as caught:
            SchemeSource(opener=opener).fetch(url('x-scheme'), 100)
        self.assertEqual((caught.exception.status, len(opener.calls)), (404, 1))

    def test_network_errors_become_source_errors(self) -> None:
        opener = _Opener(*[urllib.error.URLError('down')] * 3)
        with self.assertRaises(SourceError):
            SchemeSource(opener=opener).fetch(url('x-scheme'), 100)

    def test_robots_rules_are_honoured(self) -> None:
        source = SchemeSource(opener=_Opener(_Response(b'User-agent: *\nDisallow: /secret-scheme\n')))
        source.load_robots()
        self.assertFalse(source.allowed_by_robots(url('secret-scheme')))
        self.assertTrue(source.allowed_by_robots(url('open-scheme')))

    def test_missing_robots_allows_all_but_other_failures_abort(self) -> None:
        missing = SchemeSource(opener=_Opener(urllib.error.HTTPError('u', 404, 'nf', {}, None)))  # type: ignore[arg-type]
        missing.load_robots()
        self.assertTrue(missing.allowed_by_robots(url('anything-scheme')))
        broken = SchemeSource(opener=_Opener(*[urllib.error.HTTPError('u', 500, 'err', {}, None)] * 3))  # type: ignore[arg-type]
        with self.assertRaises(SourceError):
            broken.load_robots()


# ======================================================================== runner

@override_settings(MEDIA_ROOT=MEDIA_TMP)
class SyncBase(TestCase):
    def setUp(self) -> None:
        clean_media()
        self.addCleanup(clean_media)
        for name, value in (('scheme_sync_delay_seconds', 0.0), ('scheme_sync_max_consecutive_errors', 3)):
            patcher = mock.patch.object(Configurations, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sleeps: list[float] = []

    def run_sync(self, source: FakeSource, **kwargs):
        return SchemeSyncRunner(source=source, sleep=self.sleeps.append, **kwargs).run()

    def source(self, slugs: dict[str, tuple[str, str] | None], **extra) -> FakeSource:
        """slugs: slug -> (lastmod, html) ; extra entries can be added by overriding afterwards."""
        entries = [(url(slug), value[0]) for slug, value in slugs.items() if value]
        pages = {url(slug): value[1] for slug, value in slugs.items() if value}
        return FakeSource(sitemap(*entries), pages, **extra)


class SyncRunnerTests(SyncBase):
    def test_first_run_inserts_everything_as_pending_review(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha')), 'beta-scheme': ('2024-05-02', page('Beta'))})
        run = self.run_sync(source)
        self.assertEqual((run.status, run.created, run.fetched, run.errors), ('success', 2, 2, 0))
        schemes = Scheme.objects.order_by('title')
        self.assertEqual([s.title for s in schemes], ['Alpha', 'Beta'])
        for scheme in schemes:
            self.assertEqual((scheme.status, scheme.is_manual, scheme.locally_edited), ('pending_review', False, False))
            self.assertTrue(scheme.source_url.startswith(HOST) and scheme.content_hash and scheme.last_synced_at)
        self.assertEqual(Scheme.objects.get(title='Alpha').source_lastmod, datetime(2024, 5, 1, tzinfo=dt_timezone.utc))

    def test_second_run_with_unchanged_sitemap_fetches_nothing_and_never_duplicates(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        self.run_sync(source)
        source.fetched.clear()
        run = self.run_sync(source)
        self.assertEqual((source.fetched, run.unchanged, run.created, run.updated), ([], 1, 0, 0))
        self.assertEqual(Scheme.objects.count(), 1)

    def test_changed_source_updates_content_and_keeps_published_status(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        self.run_sync(source)
        Scheme.objects.update(status='published')
        newer = self.source({'alpha-scheme': ('2024-06-01', page('Alpha', benefits=('Now Rs. 9000',)))})
        run = self.run_sync(newer)
        scheme = Scheme.objects.get()
        self.assertEqual((run.updated, run.created, scheme.status), (1, 0, 'published'))
        self.assertIn('Now Rs. 9000', scheme.benefits)
        self.assertEqual(scheme.source_lastmod, datetime(2024, 6, 1, tzinfo=dt_timezone.utc))

    def test_newer_lastmod_with_identical_content_is_unchanged(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        before = Scheme.objects.get().content_hash
        run = self.run_sync(self.source({'alpha-scheme': ('2024-06-01', page('Alpha'))}))
        self.assertEqual((run.updated, run.unchanged), (0, 1))
        self.assertEqual(Scheme.objects.get().content_hash, before)

    def test_new_url_is_inserted_alongside_existing(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        run = self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha')), 'gamma-scheme': ('2024-07-01', page('Gamma'))}))
        self.assertEqual((run.created, Scheme.objects.count()), (1, 2))

    def test_duplicate_urls_in_sitemap_make_one_record(self) -> None:
        pages = {url('alpha-scheme'): page('Alpha')}
        source = FakeSource(sitemap((url('alpha-scheme'), '2024-05-01'), (url('alpha-scheme') + '/', '2024-05-01'), (HOST.upper() + '/alpha-scheme?utm=1', None)), pages)
        run = self.run_sync(source)
        self.assertEqual((run.created, Scheme.objects.count(), len(source.fetched)), (1, 1, 1))

    def test_only_approved_scheme_urls_are_ever_fetched(self) -> None:
        source = FakeSource(
            sitemap(
                (HOST + '/', None), (url('webstory/some-story'), None), (url('node/37750'), None), ('https://evil.example/trap-scheme', None),
                ('http://www.govtschemes.in/insecure-scheme', None), (url('real-scheme'), '2024-05-01'),
            ),
            {url('real-scheme'): page('Real')},
        )
        run = self.run_sync(source)
        self.assertEqual((source.fetched, run.created, run.scheme_urls, run.sitemap_urls), ([url('real-scheme')], 1, 1, 6))

    def test_excluded_urls_are_skipped_until_the_exclusion_is_removed(self) -> None:
        SchemeExclusion.objects.create(source_url=url('alpha-scheme'), reason='deleted')
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        run = self.run_sync(source)
        self.assertEqual((run.skipped_excluded, source.fetched, Scheme.objects.count()), (1, [], 0))
        SchemeExclusion.objects.all().delete()
        self.assertEqual(self.run_sync(source).created, 1)

    def test_admin_edited_scheme_is_not_overwritten_until_released(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        Scheme.objects.update(locally_edited=True, title='Edited by admin')
        newer = self.source({'alpha-scheme': ('2024-06-01', page('Alpha', benefits=('Source changed',)))})
        run = self.run_sync(newer)
        scheme = Scheme.objects.get()
        self.assertEqual((run.skipped_edited, run.updated, scheme.title), (1, 0, 'Edited by admin'))
        self.assertNotIn('Source changed', scheme.benefits)
        Scheme.objects.update(locally_edited=False, source_lastmod=None)
        self.assertEqual(self.run_sync(newer).updated, 1)
        self.assertEqual(Scheme.objects.get().title, 'Alpha')

    def test_manual_scheme_with_same_url_is_never_overwritten(self) -> None:
        Scheme.objects.create(title='Mine', source_url=url('alpha-scheme'), is_manual=True, description='hand written')
        run = self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        self.assertEqual((run.skipped_edited, Scheme.objects.get().title), (1, 'Mine'))

    def test_unparsable_page_is_counted_and_creates_nothing(self) -> None:
        run = self.run_sync(self.source({'about-us-page': ('2024-05-01', '<html><body><h1>About</h1></body></html>')}))
        self.assertEqual((run.skipped_invalid, run.created, Scheme.objects.count(), run.status), (1, 0, 0, 'success'))
        self.assertIn('about-us-page', run.error_summary)

    def test_fetch_error_makes_run_partial_but_other_pages_still_import(self) -> None:
        source = FakeSource(
            sitemap((url('broken-scheme'), '2024-05-01'), (url('good-scheme'), '2024-05-01')),
            {url('broken-scheme'): SourceError('HTTP 500', status=500), url('good-scheme'): page('Good')},
        )
        run = self.run_sync(source)
        self.assertEqual((run.status, run.errors, run.created), ('partial', 1, 1))
        self.assertIn('broken-scheme', run.error_summary)

    def test_run_stops_after_too_many_consecutive_errors(self) -> None:
        slugs = [f's{i}-scheme' for i in range(8)]
        source = FakeSource(sitemap(*[(url(s), '2024-05-01') for s in slugs]), {url(s): SourceError('down') for s in slugs})
        run = self.run_sync(source)
        self.assertEqual((run.status, len(source.fetched)), ('failed', 3))
        self.assertIn('consecutive', run.error_summary)

    def test_sitemap_failures_close_the_run_as_failed(self) -> None:
        for broken in (SourceError('HTTP 503'), b'<!DOCTYPE x [<!ENTITY a "b">]><urlset/>', sitemap(), b'garbage'):
            run = self.run_sync(FakeSource(broken, {}))
            self.assertEqual(run.status, 'failed', broken)
            self.assertIsNotNone(run.finished_date_time)
        self.assertEqual(Scheme.objects.count(), 0)

    def test_robots_blocked_urls_are_skipped(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}, blocked=(url('alpha-scheme'),))
        run = self.run_sync(source)
        self.assertEqual((source.fetched, run.skipped_invalid, Scheme.objects.count()), ([], 1, 0))

    def test_limit_and_max_pages_cap_the_fetches(self) -> None:
        slugs = {f's{i}-scheme': ('2024-05-01', page(f'S{i}')) for i in range(6)}
        run = self.run_sync(self.source(slugs), limit=2)
        self.assertEqual((run.fetched, Scheme.objects.count()), (2, 2))
        with mock.patch.object(Configurations, 'scheme_sync_max_pages', 3):
            self.run_sync(self.source(slugs))
        self.assertEqual(Scheme.objects.count(), 5)

    def test_force_refetches_even_when_lastmod_is_unchanged(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        self.run_sync(source)
        source.fetched.clear()
        self.run_sync(source, force=True)
        self.assertEqual(source.fetched, [url('alpha-scheme')])

    def test_urls_dropped_from_the_sitemap_are_not_deleted(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha')), 'beta-scheme': ('2024-05-01', page('Beta'))}))
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        self.assertEqual(Scheme.objects.count(), 2)

    def test_polite_delay_between_requests(self) -> None:
        with mock.patch.object(Configurations, 'scheme_sync_delay_seconds', 1.5):
            self.run_sync(self.source({f's{i}-scheme': ('2024-05-01', page(f'S{i}', images=())) for i in range(3)}))
        self.assertEqual(self.sleeps, [1.5, 1.5])

    def test_missing_lastmod_means_always_refetch(self) -> None:
        source = FakeSource(sitemap((url('alpha-scheme'), None)), {url('alpha-scheme'): page('Alpha')})
        self.run_sync(source)
        self.run_sync(source)
        self.assertEqual(len(source.fetched), 2)
        self.assertEqual(Scheme.objects.count(), 1)

    def test_only_one_run_at_a_time_and_stale_runs_do_not_block(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        busy = SchemeSyncRun.objects.create(status='running')
        with self.assertRaises(SyncBusyError):
            self.run_sync(source)
        SchemeSyncRun.objects.filter(pk=busy.pk).update(started_date_time=timezone.now() - timedelta(hours=4))
        self.assertEqual(self.run_sync(source).status, 'success')

    def test_crash_still_closes_the_run(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        with mock.patch('gmp_apps.schemes.sync.runner.parse_scheme_page', side_effect=RuntimeError('boom')), self.assertLogs('gmp_apps.schemes.sync.runner', 'ERROR'):
            run = self.run_sync(source)
        self.assertEqual(run.status, 'failed')
        self.assertIsNotNone(run.finished_date_time)
        self.assertIn('RuntimeError', run.error_summary)
        self.assertFalse(SchemeSyncRun.objects.filter(status='running').exists())

    def test_database_unique_source_url(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Scheme.objects.create(title='Dup', source_url=url('alpha-scheme'))
        Scheme.objects.create(title='No url 1')  # manual schemes may have no URL
        Scheme.objects.create(title='No url 2')


class TaskAndCommandTests(SyncBase):
    def fake_factory(self, source: FakeSource):
        return mock.patch('gmp_apps.schemes.sync.runner.SchemeSource', return_value=source)

    def test_celery_task_runs_a_sync_and_reports(self) -> None:
        source = self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))})
        with self.fake_factory(source), mock.patch('gmp_apps.schemes.sync.runner.time.sleep'):
            result = sync_schemes.apply().get()
        self.assertEqual((result['status'], result['created']), ('success', 1))
        self.assertEqual(SchemeSyncRun.objects.get().trigger, 'beat')

    def test_celery_task_does_not_overlap_a_running_sync(self) -> None:
        SchemeSyncRun.objects.create(status='running')
        with self.assertLogs('gmp_apps.schemes.tasks', 'WARNING'):
            self.assertEqual(sync_schemes.apply().get(), {'skipped': 'busy'})

    def test_task_is_registered_and_scheduled_every_24_hours(self) -> None:
        from django.conf import settings

        from gmp.celery import app

        app.loader.import_default_modules()
        self.assertIn('gmp_apps.schemes.tasks.sync_schemes', app.tasks)
        entry = settings.CELERY_BEAT_SCHEDULE['sync-schemes']
        self.assertEqual(entry['task'], 'gmp_apps.schemes.tasks.sync_schemes')
        self.assertEqual(entry['schedule'], Configurations.scheme_sync_interval_hours * 3600)
        self.assertEqual(Configurations.scheme_sync_interval_hours, 24)

    def test_import_command_bulk_imports_and_prints_summary(self) -> None:
        source = self.source({f's{i}-scheme': ('2024-05-01', page(f'S{i}')) for i in range(3)})
        out = StringIO()
        with self.fake_factory(source), mock.patch('gmp_apps.schemes.sync.runner.time.sleep'):
            call_command('import_schemes', limit=2, stdout=out)
        self.assertIn('created 2', out.getvalue())
        self.assertEqual(Scheme.objects.count(), 2)

    def test_import_command_fails_loudly_on_failed_run_or_busy(self) -> None:
        with self.fake_factory(FakeSource(SourceError('HTTP 503'), {})), self.assertRaises(CommandError):
            call_command('import_schemes', stdout=StringIO())
        SchemeSyncRun.objects.create(status='running')
        with self.assertRaises(CommandError):
            call_command('import_schemes', stdout=StringIO())


# ======================================================================== API

@override_settings(PASSWORD_HASHERS=FAST_HASHERS, MEDIA_ROOT=MEDIA_TMP)
class SchemeApiBase(APITestCase):
    def setUp(self) -> None:
        clean_media()
        self.addCleanup(clean_media)
        cache.clear()
        call_command('setup_admin_groups', stdout=StringIO())
        self.counter = 0

    def member(self) -> User:
        self.counter += 1
        return User.objects.create_user(full_name=f'Member {self.counter}', password=PASSWORD, email=f'm{self.counter}@example.com', email_verified=True)

    def staff(self, *groups: str, role: str = 'admin') -> User:
        self.counter += 1
        user = User.objects.create_user(
            full_name='Reviewer', password=PASSWORD, email=f'st{self.counter}@example.com', is_staff=True, role=role, email_verified=True,
        )
        user.groups.add(*Group.objects.filter(name__in=groups))
        return user

    @staticmethod
    def as_user(user: User | None) -> APIClient:
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def scheme(self, title: str = 'Scheme', status: str = 'published', **extra) -> Scheme:
        defaults = {'description': f'About {title}', 'benefits': '- money', 'eligibility': '- everyone', 'application_procedure': '- apply',
                    'required_documents': '- id', 'department': 'Dept A',
                    'source_url': url(title.lower().replace(' ', '-')), 'status': status}
        defaults.update(extra)
        return Scheme.objects.create(title=title, **defaults)

    @staticmethod
    def add_image(scheme: Scheme, tag: str = 'a', position: int = 0, source_url: str | None = None) -> SchemeImage:
        return SchemeImage.objects.create(
            scheme=scheme, file=ContentFile(png(tag), name='x'), position=position, source_url=source_url,
        )


class SchemeMemberApiTests(SchemeApiBase):
    LIST = '/schemes/get_all/'

    def test_only_published_schemes_are_listed(self) -> None:
        self.scheme('Visible one')
        self.scheme('Pending one', status='pending_review')
        self.scheme('Hidden one', status='unpublished')
        rows = self.as_user(self.member()).get(self.LIST).data['data']['data']
        self.assertEqual([r['title'] for r in rows], ['Visible one'])

    def test_list_row_shape_and_no_internal_fields(self) -> None:
        scheme = self.scheme('Visible one', content_hash='abc', locally_edited=True, is_manual=True)
        image = self.add_image(scheme)
        response = self.as_user(self.member()).get(self.LIST)
        row = response.data['data']['data'][0]
        self.assertEqual(set(row), {'schemeId', 'title', 'department', 'summary', 'imageUrl', 'tags', 'isActive', 'updatedDateTime'})
        self.assertEqual((row['summary'], row['imageUrl']), ('About Visible one', f'http://testserver{image.file.url}'))
        payload = str(response.data['data'])
        for internal in ('status', 'locallyEdited', 'contentHash', 'isManual', 'reviewedBy', 'sourceLastmod', 'pending_review'):
            self.assertNotIn(internal, payload)

    def test_summary_is_short_and_flat(self) -> None:
        self.scheme('Long one', description='- first point\n- ' + 'word ' * 100)
        row = self.as_user(self.member()).get(self.LIST).data['data']['data'][0]
        self.assertLessEqual(len(row['summary']), 222)
        self.assertNotIn('\n', row['summary'])
        self.assertTrue(row['summary'].startswith('first point'))

    def test_pagination_filter_search_sort_values(self) -> None:
        for index in range(5):
            self.scheme(f'Alpha {index}', department='Dept A' if index < 3 else 'Dept B')
        client = self.as_user(self.member())
        page = client.get(f'{self.LIST}?limit=2').data['data']
        self.assertEqual((len(page['data']), page['totalPage']), (2, 3))
        self.assertIn('nextPageUrl', page)
        dept = client.get(f'{self.LIST}?filter_key=department&filter_value=Dept B').data['data']['data']
        self.assertEqual(len(dept), 2)
        found = client.get(f'{self.LIST}?search_key=Alpha 3').data['data']['data']
        self.assertEqual([r['title'] for r in found], ['Alpha 3'])
        ordered = client.get(f'{self.LIST}?sort_by=title&sort_order=desc').data['data']['data']
        self.assertEqual(ordered[0]['title'], 'Alpha 4')
        values = client.get(f'{self.LIST}?values=schemeId,title').data['data']['data']
        self.assertEqual(set(values[0]), {'schemeId', 'title'})
        self.assertEqual(client.get(f'{self.LIST}?sort_by=status').status_code, 400)
        self.assertEqual(client.get(f'{self.LIST}?filter_key=status&filter_value=pending_review').status_code, 400)
        self.assertEqual(client.get(f'{self.LIST}?page_num=9').status_code, 400)

    def test_search_only_matches_member_visible_text_not_internal_fields(self) -> None:
        self.scheme('Visible one', content_hash='deadbeefcafe1234', source_url=url('hidden-slug-token'))
        client = self.as_user(self.member())
        for internal in ('deadbeefcafe1234', 'pending_review', 'published'):
            self.assertEqual(client.get(f'{self.LIST}?search_key={internal}').data['data']['data'], [], internal)
        self.assertEqual(len(client.get(f'{self.LIST}?search_key=Visible').data['data']['data']), 1)

    def test_search_does_not_find_unpublished_content(self) -> None:
        self.scheme('Secret pending', status='pending_review', description='confidential wording')
        self.assertEqual(self.as_user(self.member()).get(f'{self.LIST}?search_key=confidential').data['data']['data'], [])

    def test_get_published_scheme_full_detail(self) -> None:
        scheme = self.scheme('Detail one')
        image = self.add_image(scheme)
        response = self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}')
        data = response.data['data']
        self.assertEqual((data['title'], data['eligibility'], data['applicationProcedure'], data['requiredDocuments'], data['department']),
                         ('Detail one', '- everyone', '- apply', '- id', 'Dept A'))
        self.assertEqual(data['images'], [f'http://testserver{image.file.url}'])
        self.assertNotIn('sourceUrl', data)
        for internal in ('status', 'contentHash', 'locallyEdited', 'reviewedBy', 'sourceUrl'):
            self.assertNotIn(internal, data)

    def test_unpublished_pending_and_unknown_are_404(self) -> None:
        client = self.as_user(self.member())
        for status in ('pending_review', 'unpublished'):
            scheme = self.scheme(f'Not live {status}', status=status)
            self.assertEqual(client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').status_code, 404)
        self.assertEqual(client.get('/schemes/get/?scheme_id=999999').status_code, 404)
        self.assertEqual(client.get('/schemes/get/').status_code, 400)

    def test_authentication_and_roles(self) -> None:
        scheme = self.scheme('Detail one')
        for path in (self.LIST, f'/schemes/get/?scheme_id={scheme.scheme_id}'):
            self.assertEqual(self.as_user(None).get(path).status_code, 401)
            self.assertEqual(self.as_user(self.staff('Scheme Reviewers')).get(path).status_code, 403)


class SchemeDeleteApiTests(SchemeApiBase):
    def delete(self, user: User | None, scheme_id: int | str):
        return self.as_user(user).delete(f'/schemes/delete/?scheme_id={scheme_id}')

    def test_permission_matrix(self) -> None:
        scheme = self.scheme('Target')
        self.assertEqual(self.delete(None, scheme.scheme_id).status_code, 401)
        self.assertEqual(self.delete(self.member(), scheme.scheme_id).status_code, 403)
        self.assertEqual(self.delete(self.staff(), scheme.scheme_id).status_code, 403)
        self.assertEqual(self.delete(self.staff('Support Handlers'), scheme.scheme_id).status_code, 403)
        self.assertEqual(self.delete(self.staff('Scheme Reviewers', role='member'), scheme.scheme_id).status_code, 403)
        self.assertTrue(Scheme.objects.filter(pk=scheme.pk).exists())
        self.assertEqual(self.delete(self.staff('Scheme Reviewers'), scheme.scheme_id).status_code, 200)

    def test_delete_removes_local_record_blocks_reimport_and_never_touches_the_network(self) -> None:
        scheme = self.scheme('Target')
        with mock.patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network used')) as network:
            response = self.delete(self.staff('Scheme Reviewers'), scheme.scheme_id)
        self.assertEqual(response.status_code, 200)
        network.assert_not_called()
        self.assertFalse(Scheme.objects.exists())
        self.assertEqual(SchemeExclusion.objects.get().source_url, url('target'))
        source = FakeSource(sitemap((url('target'), '2024-05-01')), {url('target'): page('Target')})
        with mock.patch.object(Configurations, 'scheme_sync_delay_seconds', 0.0):
            SchemeSyncRunner(source=source, sleep=lambda s: None).run()
        self.assertEqual((source.fetched, Scheme.objects.count()), ([], 0))

    def test_manual_scheme_without_url_deletes_without_exclusion(self) -> None:
        scheme = self.scheme('Manual', source_url=None, is_manual=True)
        self.assertEqual(self.delete(self.staff('Scheme Reviewers'), scheme.scheme_id).status_code, 200)
        self.assertEqual((Scheme.objects.count(), SchemeExclusion.objects.count()), (0, 0))

    def test_unknown_id_and_bad_input(self) -> None:
        reviewer = self.staff('Scheme Reviewers')
        self.assertEqual(self.delete(reviewer, 999999).status_code, 404)
        self.assertEqual(self.as_user(reviewer).delete('/schemes/delete/').status_code, 400)
        self.assertEqual(self.delete(reviewer, 'abc').status_code, 400)

    def test_any_status_can_be_deleted_by_a_permitted_admin(self) -> None:
        reviewer = self.staff('Scheme Reviewers')
        for status in ('pending_review', 'published', 'unpublished'):
            scheme = self.scheme(f'S {status}', status=status)
            self.assertEqual(self.delete(reviewer, scheme.scheme_id).status_code, 200, status)


# ======================================================================== admin

@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SchemeAdminTests(SchemeApiBase):
    LIST = '/admin/schemes/scheme/'

    def setUp(self) -> None:
        super().setUp()
        self.reviewer = self.staff('Scheme Reviewers')

    @staticmethod
    def client_for(user: User | None) -> Client:
        client = Client()
        if user:
            client.force_login(user)
        return client

    def change_url(self, scheme: Scheme) -> str:
        return f'{self.LIST}{scheme.pk}/change/'

    def form(self, scheme: Scheme | None = None, **overrides) -> dict:
        data = {'title': 'T', 'department': 'D', 'description': 'desc', 'eligibility': '', 'benefits': '', 'application_procedure': '',
                'required_documents': '', 'highlights': '', 'contact_details': '', 'links_text': '',
                'overview_text': '', 'additional_text': '[]', 'source_url': '', '_save': 'Save',
                'tags-TOTAL_FORMS': '0', 'tags-INITIAL_FORMS': '0', 'tags-MIN_NUM_FORMS': '0', 'tags-MAX_NUM_FORMS': '1000',
                'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0', 'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '10', 'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0', 'documents-MIN_NUM_FORMS': '0', 'documents-MAX_NUM_FORMS': '10'}
        if scheme:
            data.update({'title': scheme.title, 'department': scheme.department, 'description': scheme.description,
                         'eligibility': scheme.eligibility, 'benefits': scheme.benefits,
                         'application_procedure': scheme.application_procedure, 'required_documents': scheme.required_documents,
                         'highlights': scheme.highlights, 'contact_details': scheme.contact_details})
        data.update(overrides)
        return data

    def run_action(self, user: User, action: str, *schemes: Scheme):
        return self.client_for(user).post(self.LIST, {'action': action, '_selected_action': [s.pk for s in schemes]}, follow=True)

    def test_review_list_filters_and_search(self) -> None:
        self.scheme('Pending one', status='pending_review')
        self.scheme('Live one')
        client = self.client_for(self.reviewer)
        self.assertEqual(client.get(self.LIST).status_code, 200)
        pending = client.get(f'{self.LIST}?status__exact=pending_review').context['cl'].result_list
        self.assertEqual([s.title for s in pending], ['Pending one'])
        found = client.get(f'{self.LIST}?q=live-one').context['cl'].result_list
        self.assertEqual([s.title for s in found], ['Live one'])

    def test_publish_unpublish_flow_controls_member_visibility(self) -> None:
        scheme = self.scheme('Flow one', status='pending_review')
        member = self.as_user(self.member())
        self.assertEqual(member.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').status_code, 404)
        self.run_action(self.reviewer, 'publish_selected', scheme)
        scheme.refresh_from_db()
        self.assertEqual((scheme.status, scheme.reviewed_by_id), ('published', self.reviewer.user_id))
        self.assertIsNotNone(scheme.published_date_time)
        self.assertEqual(member.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').status_code, 200)
        self.run_action(self.reviewer, 'unpublish_selected', scheme)
        scheme.refresh_from_db()
        self.assertEqual(scheme.status, 'unpublished')
        self.assertEqual(member.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').status_code, 404)

    def test_publish_skips_schemes_without_any_content(self) -> None:
        empty = self.scheme('Empty one', status='pending_review', description='', benefits='', eligibility='')
        ok = self.scheme('Fine one', status='pending_review')
        response = self.run_action(self.reviewer, 'publish_selected', empty, ok)
        empty.refresh_from_db()
        ok.refresh_from_db()
        self.assertEqual((empty.status, ok.status), ('pending_review', 'published'))
        self.assertContains(response, '1 had no description')

    def test_publish_needs_the_publish_permission(self) -> None:
        scheme = self.scheme('Flow one', status='pending_review')
        no_publish = self.staff()
        no_publish.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='schemes', codename__in=['view_scheme', 'change_scheme']))
        self.run_action(no_publish, 'publish_selected', scheme)
        scheme.refresh_from_db()
        self.assertEqual(scheme.status, 'pending_review')

    def test_editing_an_imported_scheme_protects_it_from_sync(self) -> None:
        scheme = self.scheme('Imported one', content_hash='x')
        response = self.client_for(self.reviewer).post(self.change_url(scheme), self.form(scheme, title='Edited title'), follow=True)
        scheme.refresh_from_db()
        self.assertEqual((scheme.title, scheme.locally_edited, scheme.is_manual), ('Edited title', True, False))
        self.assertContains(response, 'now protected')

    def test_saving_without_changes_does_not_flag_the_scheme(self) -> None:
        scheme = self.scheme('Imported one')
        self.client_for(self.reviewer).post(self.change_url(scheme), self.form(scheme), follow=True)
        scheme.refresh_from_db()
        self.assertFalse(scheme.locally_edited)

    def test_release_local_edits_action(self) -> None:
        scheme = self.scheme('Imported one', locally_edited=True, source_lastmod=timezone.now())
        manual = self.scheme('Manual one', source_url=None, is_manual=True, locally_edited=True)
        self.run_action(self.reviewer, 'release_local_edits', scheme, manual)
        scheme.refresh_from_db()
        manual.refresh_from_db()
        self.assertEqual((scheme.locally_edited, scheme.source_lastmod), (False, None))
        self.assertTrue(manual.locally_edited)

    def test_manual_add_creates_a_pending_manual_scheme(self) -> None:
        data = self.form(title='Hand made', source_url=url('hand-made'))
        self.client_for(self.reviewer).post(self.LIST + 'add/', data, follow=True)
        scheme = Scheme.objects.get(title='Hand made')
        self.assertEqual((scheme.status, scheme.is_manual, scheme.reviewed_by_id), ('pending_review', True, self.reviewer.user_id))

    def test_manual_add_rejects_a_duplicate_source_url(self) -> None:
        self.scheme('Existing one')
        self.client_for(self.reviewer).post(self.LIST + 'add/', self.form(title='Duplicate url', source_url=url('existing-one')))
        self.assertEqual(Scheme.objects.count(), 1)

    def test_source_url_and_review_fields_cannot_be_tampered_with(self) -> None:
        scheme = self.scheme('Imported one', status='pending_review')
        self.client_for(self.reviewer).post(self.change_url(scheme), self.form(
            scheme, source_url='https://evil.example/x', status='published', is_manual='on', locally_edited='', reviewed_by=self.reviewer.pk,
        ))
        scheme.refresh_from_db()
        self.assertEqual((scheme.source_url, scheme.status, scheme.is_manual), (url('imported-one'), 'pending_review', False))

    def test_delete_in_admin_removes_local_record_and_blocks_reimport(self) -> None:
        scheme = self.scheme('Doomed one')
        self.client_for(self.reviewer).post(self.change_url(scheme).replace('change/', 'delete/'), {'post': 'yes'}, follow=True)
        self.assertFalse(Scheme.objects.exists())
        self.assertEqual(SchemeExclusion.objects.get().source_url, url('doomed-one'))

    def test_bulk_delete_in_admin_also_blocks_reimport(self) -> None:
        first, second = self.scheme('Doomed one'), self.scheme('Doomed two')
        self.client_for(self.reviewer).post(
            self.LIST, {'action': 'delete_selected', '_selected_action': [first.pk, second.pk], 'post': 'yes'}, follow=True,
        )
        self.assertFalse(Scheme.objects.exists())
        self.assertEqual(SchemeExclusion.objects.count(), 2)

    def test_exclusion_admin_allows_removing_but_not_adding_or_editing(self) -> None:
        entry = SchemeExclusion.objects.create(source_url=url('gone-one'), reason='x')
        client = self.client_for(self.reviewer)
        base = '/admin/schemes/schemeexclusion/'
        self.assertEqual(client.get(base).status_code, 200)
        self.assertEqual(client.get(base + 'add/').status_code, 403)
        client.post(f'{base}{entry.pk}/change/', {'source_url': 'https://evil.example/x', 'reason': 'tampered'})
        entry.refresh_from_db()
        self.assertEqual((entry.source_url, entry.reason), (url('gone-one'), 'x'))
        client.post(f'{base}{entry.pk}/delete/', {'post': 'yes'}, follow=True)
        self.assertFalse(SchemeExclusion.objects.exists())

    def test_sync_log_is_read_only_and_visible(self) -> None:
        SchemeSyncRun.objects.create(status='success', created=3)
        client = self.client_for(self.reviewer)
        self.assertEqual(client.get('/admin/schemes/schemesyncrun/').status_code, 200)
        run = SchemeSyncRun.objects.get()
        self.assertEqual(client.get('/admin/schemes/schemesyncrun/add/').status_code, 403)
        self.assertEqual(client.post(f'/admin/schemes/schemesyncrun/{run.pk}/delete/', {'post': 'yes'}).status_code, 403)
        self.assertTrue(SchemeSyncRun.objects.filter(pk=run.pk).exists())

    def test_only_scheme_reviewers_and_superusers_can_use_the_scheme_admin(self) -> None:
        scheme = self.scheme('Imported one', status='pending_review')
        for blocked in (self.staff(), self.staff('Member Managers'), self.staff('Membership Reviewers'), self.staff('Support Handlers')):
            client = self.client_for(blocked)
            self.assertEqual(client.get(self.LIST).status_code, 403)
            self.run_action(blocked, 'publish_selected', scheme)
        scheme.refresh_from_db()
        self.assertEqual(scheme.status, 'pending_review')
        self.assertEqual(Client().get(self.LIST).status_code, 302)
        self.assertEqual(self.client_for(self.member()).get(self.LIST).status_code, 302)
        superuser = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        self.assertEqual(self.client_for(superuser).get(self.LIST).status_code, 200)

    def test_scheme_reviewers_cannot_see_members_or_other_areas(self) -> None:
        client = self.client_for(self.reviewer)
        for path in ('/admin/authentication/user/', '/admin/membership/referral/', '/admin/contact_admin/contactrequest/'):
            self.assertEqual(client.get(path).status_code, 403, path)

    def test_dashboard_cards_follow_permission(self) -> None:
        self.scheme('Pending one', status='pending_review')
        self.scheme('Live one')

        def cards(user: User) -> dict[str, int]:
            return {c['title']: c['value'] for c in self.client_for(user).get('/admin/').context['dashboard_cards']}

        self.assertEqual(cards(self.reviewer), {'Schemes awaiting review': 1, 'Published schemes': 1, 'Schemes waiting for pictures/PDFs': 2, 'Last scheme sync': 'Never run'})
        self.assertNotIn('Schemes awaiting review', cards(self.staff('Member Managers')))


class SwaggerTests(SchemeApiBase):
    def test_paths_in_schema(self) -> None:
        body = APIClient().get('/api/schema/').content.decode()
        for path in ('get_all', 'get', 'delete'):
            self.assertIn(f'/schemes/{path}/', body)


# ======================================================================== fidelity: everything on the page is kept

def cf_encode(email: str, key: int = 0x17) -> str:
    """Cloudflare-style email obfuscation, as served by the source."""
    return f'{key:02x}' + ''.join(f'{ord(c) ^ key:02x}' for c in email)


def cf_anchor(email: str) -> str:
    return f'<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{cf_encode(email)}">[email&#160;protected]</a>'


class ParserFidelityTests(TestCase):
    def parse(self, html: str):
        return parse_scheme_page(html, url('sample-scheme'))

    @staticmethod
    def stored_text(scheme) -> str:
        parts = [scheme.description, scheme.eligibility, scheme.benefits, scheme.application_procedure, scheme.required_documents,
                 scheme.highlights, scheme.contact_details]
        parts += [f"{s['heading']} {s['text']}" for s in scheme.additional_sections]
        parts += [f"{r['label']} {r['value']}" for r in scheme.overview]
        parts += [f"{l['label']} {l['url']}" for l in scheme.links]
        return ' '.join(parts)

    def test_unrecognised_sections_are_kept_in_page_order(self) -> None:
        scheme = self.parse(page(extra=(
            ('Selection Process', ('Committee reviews', 'Interview round')), ('Application Fee', ('Rs. 100 per form',)),
        )))
        self.assertEqual([s['heading'] for s in scheme.additional_sections], ['Selection Process', 'Application Fee'])
        self.assertEqual(scheme.additional_sections[0]['text'], '- Committee reviews\n- Interview round')
        self.assertEqual(scheme.additional_sections[1]['text'], '- Rs. 100 per form')

    def test_no_visible_text_is_silently_lost(self) -> None:
        marker_extra = tuple((f'Extra Heading {i}', (f'unique-detail-{i} about section',)) for i in range(5))
        scheme = self.parse(page(
            intro='intro-marker', benefits=('benefit-marker',), eligibility=('eligibility-marker',), documents=('document-marker',),
            how=('how-marker',), extra=marker_extra, highlights='highlight-marker', contact=('contact-marker',),
            table=(('Ministry', 'ministry-marker'), ('Mode', 'mode-marker')), preamble='preamble-marker',
        ))
        text = self.stored_text(scheme)
        for marker in ('intro-marker', 'benefit-marker', 'eligibility-marker', 'document-marker', 'how-marker', 'highlight-marker',
                       'contact-marker', 'ministry-marker', 'mode-marker', 'preamble-marker', *[f'unique-detail-{i}' for i in range(5)]):
            self.assertIn(marker, text, marker)

    def test_faq_questions_are_kept_as_sections_and_the_banner_is_not(self) -> None:
        scheme = self.parse(page(extra=(('Frequently Asked Questions', ()), ('1. How much pension?', ('Rs. 1,000 monthly',)))))
        self.assertEqual([s['heading'] for s in scheme.additional_sections], ['1. How much pension?'])
        self.assertIn('Rs. 1,000 monthly', scheme.additional_sections[0]['text'])

    def test_widened_heading_synonyms_reach_the_core_fields(self) -> None:
        scheme = self.parse(page(
            how=(), eligibility=(), benefits=(),
            extra=(
                ('Online Application Process', ('Register online',)), ('Who Is Not Eligible', ('Existing pensioners',)),
                ('Features of the Scheme', ('Monthly cash',)), ('Amount of Scholarship', ('Rs. 6000',)),
            ),
        ))
        self.assertIn('Register online', scheme.application_procedure)
        self.assertIn('Existing pensioners', scheme.eligibility)
        self.assertIn('Monthly cash', scheme.benefits)
        self.assertIn('Rs. 6000', scheme.benefits)
        self.assertEqual(scheme.additional_sections, [])

    def test_several_sections_for_one_field_keep_their_sub_headings(self) -> None:
        scheme = self.parse(page(how=(), extra=(('Online Application Process', ('Open portal',)), ('Offline Application Process', ('Visit office',)))))
        self.assertEqual(scheme.application_procedure, 'Online Application Process\n- Open portal\n\nOffline Application Process\n- Visit office')

    def test_preamble_text_becomes_description_or_an_overview_section(self) -> None:
        only_preamble = self.parse(page(intro='', preamble='Standalone intro paragraph', highlights=''))
        self.assertEqual(only_preamble.description, 'Standalone intro paragraph')
        both = self.parse(page(preamble='Standalone intro paragraph'))
        self.assertEqual(both.description, 'A scheme that helps farmers.')
        self.assertEqual(both.additional_sections[0], {'heading': 'Overview', 'text': 'Standalone intro paragraph'})

    def test_highlights_are_stored_and_still_back_up_benefits(self) -> None:
        scheme = self.parse(page(benefits=(), highlights='Rs.5000 for girls'))
        self.assertEqual(scheme.highlights, '- Rs.5000 for girls')
        self.assertEqual(scheme.benefits, scheme.highlights)

    def test_overview_table_rows_without_noise(self) -> None:
        scheme = self.parse(page(table=(
            ('Scheme Name', 'Sample Scheme'), ('Subscription', 'Subscribe Here'), ('Nodal Department:', 'Not Known Yet.'), ('Mode', 'Online'),
        )))
        self.assertEqual(scheme.overview, [{'label': 'Scheme Name', 'value': 'Sample Scheme'}, {'label': 'Mode', 'value': 'Online'}])

    # ---------- links ----------

    def test_links_website_brochure_then_important_links_in_order(self) -> None:
        scheme = self.parse(page(
            links=(('Guidelines', 'https://portal.example/guide.pdf'), ('Mobile app', 'https://play.google.com/store/apps/details?id=x')),
            website=('Official portal', 'https://official.example/'), brochure=('Brochure PDF', '/sites/default/files/2024-02/brochure.pdf'),
        ))
        self.assertEqual([(l['kind'], l['label']) for l in scheme.links],
                         [('website', 'Official portal'), ('brochure', 'Brochure PDF'), ('link', 'Guidelines'), ('link', 'Mobile app')])
        self.assertEqual(scheme.links[1]['url'], f'{HOST}/sites/default/files/2024-02/brochure.pdf')

    def test_dangerous_and_irrelevant_links_are_never_stored(self) -> None:
        scheme = self.parse(page(links=(
            ('js', 'javascript:alert(1)'), ('mail', 'mailto:a@b.co'), ('data', 'data:text/html,<script>alert(1)</script>'),
            ('tel', 'tel:+911234567890'), ('jsh', 'javascript://evil.example/%0Aalert(1)'), ('ftp', 'ftp://files.example/x'),
            ('fileurl', 'file://host/etc/passwd'), ('vbs', 'vbscript://evil.example/x'), ('rel', '/subscription/states'), ('nav', f'{HOST}/other-scheme'),
            ('cf', '/cdn-cgi/l/email-protection'), ('space', 'https://ok.example/a b'), ('ok', 'https://ok.example/a'),
            ('dup', 'https://ok.example/a'), ('file', '/sites/default/files/2024-02/guide.pdf'), ('ctl', 'https://ok.example/\x01x'),
        )))
        self.assertEqual([l['url'] for l in scheme.links], ['https://ok.example/a', f'{HOST}/sites/default/files/2024-02/guide.pdf'])

    def test_links_are_capped_and_labels_clipped(self) -> None:
        many = tuple((f'L{i}', f'https://ok.example/{i}') for i in range(50))
        self.assertEqual(len(self.parse(page(links=many)).links), 30)
        long_label = self.parse(page(links=(('x' * 500, 'https://ok.example/a'),))).links[0]['label']
        self.assertEqual(len(long_label), 200)
        self.assertEqual(self.parse(page(links=(('', 'https://ok.example/a'),))).links[0]['label'], 'ok.example')

    def test_links_section_with_only_text_is_kept_as_a_section(self) -> None:
        scheme = self.parse(page(links=(), extra=(('Important Links', ('Application form will be released soon',)),)))
        self.assertEqual(scheme.links, [])
        self.assertIn('released soon', self.stored_text(scheme))

    # ---------- contact ----------

    def test_contact_section_and_obfuscated_email_are_decoded(self) -> None:
        scheme = self.parse(page(contact=('Helpline: 1800-111-222', f'Email: {cf_anchor("help.desk@gov.in")}')))
        self.assertEqual(scheme.contact_details, '- Helpline: 1800-111-222\n- Email: help.desk@gov.in')
        self.assertNotIn('protected', scheme.contact_details)

    def test_broken_obfuscation_never_leaks_placeholder_or_crashes(self) -> None:
        broken = '<a class="__cf_email__" data-cfemail="zzzz">[email&#160;protected]</a>'
        scheme = self.parse(page(contact=(f'Email: {broken}',)))
        self.assertNotIn('protected', scheme.contact_details)
        self.assertEqual(scheme.contact_details, '- Email:')

    def test_customer_care_block_is_the_fallback_for_contact(self) -> None:
        html = page(contact=()).replace('</article>', '<div id="icc"><div>Customer Care</div><ul><li>Toll free 1800-000</li></ul></div></article>')
        self.assertEqual(self.parse(html).contact_details, '- Toll free 1800-000')

    # ---------- tags ----------

    def test_tags_by_group_deduplicated_and_ministry_fallback(self) -> None:
        scheme = self.parse(page(
            table=(), ministry='Ministry of Labour',
            tags=(('scheme_type', 'Pension'), ('person_type', 'Labour'), ('person_type', 'Labour'), ('caste', 'SC'), ('scheme_type', 'Health')),
        ))
        self.assertEqual(sorted((t['group'], t['name']) for t in scheme.tags),
                         [('caste', 'SC'), ('person_type', 'Labour'), ('scheme_type', 'Health'), ('scheme_type', 'Pension')])
        self.assertEqual(scheme.department, 'Ministry of Labour')

    def test_table_department_wins_over_ministry_term(self) -> None:
        scheme = self.parse(page(table=(('Ministry', 'Ministry of Agriculture'),), ministry='Ministry of Labour'))
        self.assertEqual(scheme.department, 'Ministry of Agriculture')

    def test_every_new_field_is_part_of_the_content_hash(self) -> None:
        base = self.parse(page()).content_hash()
        for changed in (page(links=(('Other', 'https://other.example/x'),)), page(contact=('Different',)), page(tags=(('scheme_type', 'New'),)),
                        page(extra=(('New section', ('x',)),)), page(highlights='new highlight'), page(table=(('Mode', 'Offline'),))):
            self.assertNotEqual(self.parse(changed).content_hash(), base)


class SyncStoresEverythingTests(SyncBase):
    def full_page(self, **extra):
        return page('Rich', tags=(('scheme_type', 'Pension'), ('person_type', 'Labour')), website=('Portal', 'https://portal.example/'),
                    extra=(('Selection Process', ('Committee',)),), highlights='hl', **extra)

    def test_import_stores_every_captured_field_and_tags(self) -> None:
        self.run_sync(self.source({'rich-scheme': ('2024-05-01', self.full_page())}))
        scheme = Scheme.objects.get()
        self.assertEqual(scheme.highlights, '- hl')
        self.assertIn('CONTACTTEXT', scheme.contact_details)
        self.assertEqual(scheme.links[0]['kind'], 'website')
        self.assertEqual(scheme.additional_sections[0]['heading'], 'Selection Process')
        self.assertEqual(scheme.overview[0]['label'], 'Ministry')
        self.assertEqual(sorted(scheme.tags.values_list('group', 'name')), [('person_type', 'Labour'), ('scheme_type', 'Pension')])

    def test_source_change_in_tags_or_new_sections_updates_the_record(self) -> None:
        self.run_sync(self.source({'rich-scheme': ('2024-05-01', self.full_page())}))
        changed = page('Rich', tags=(('scheme_type', 'Health'),), website=('Portal', 'https://portal.example/'),
                       extra=(('Selection Process', ('Committee',)), ('New Section', ('added later',))), highlights='hl')
        run = self.run_sync(self.source({'rich-scheme': ('2024-06-01', changed)}))
        scheme = Scheme.objects.get()
        self.assertEqual(run.updated, 1)
        self.assertEqual(list(scheme.tags.values_list('group', 'name')), [('scheme_type', 'Health')])
        self.assertEqual([s['heading'] for s in scheme.additional_sections], ['Selection Process', 'New Section'])

    def test_unchanged_page_with_all_fields_is_unchanged_next_time(self) -> None:
        source = self.source({'rich-scheme': ('2024-05-01', self.full_page())})
        self.run_sync(source)
        run = self.run_sync(self.source({'rich-scheme': ('2024-06-01', self.full_page())}))
        self.assertEqual((run.updated, run.unchanged), (0, 1))

    def test_admin_owned_tags_are_not_touched_by_the_sync(self) -> None:
        self.run_sync(self.source({'rich-scheme': ('2024-05-01', self.full_page())}))
        scheme = Scheme.objects.get()
        Scheme.objects.filter(pk=scheme.pk).update(locally_edited=True)
        scheme.set_tags([{'group': 'caste', 'name': 'Admin tag'}])
        changed = page('Rich', tags=(('scheme_type', 'Health'),), website=('Portal', 'https://portal.example/'), highlights='different')
        self.run_sync(self.source({'rich-scheme': ('2024-06-01', changed)}))
        self.assertEqual(list(scheme.tags.values_list('group', 'name')), [('caste', 'Admin tag')])

    def test_set_tags_replaces_and_reports_change(self) -> None:
        scheme = Scheme.objects.create(title='T')
        self.assertTrue(scheme.set_tags([{'group': 'scheme_type', 'name': 'A'}, {'group': 'caste', 'name': 'B'}]))
        self.assertFalse(scheme.set_tags([{'group': 'caste', 'name': 'B'}, {'group': 'scheme_type', 'name': 'A'}]))
        self.assertTrue(scheme.set_tags([{'group': 'caste', 'name': 'B'}]))
        self.assertEqual(list(scheme.tags.values_list('group', 'name')), [('caste', 'B')])
        self.assertTrue(scheme.set_tags([]))
        self.assertEqual(scheme.tags.count(), 0)

    def test_tag_is_unique_per_scheme(self) -> None:
        from django.db import IntegrityError, transaction

        scheme = Scheme.objects.create(title='T')
        scheme.set_tags([{'group': 'caste', 'name': 'B'}])
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchemeTag = scheme.tags.model
            SchemeTag.objects.create(scheme=scheme, group='caste', name='B')


class SchemeRichApiTests(SchemeApiBase):
    def rich(self, title: str = 'Rich one', status: str = 'published', **extra) -> Scheme:
        scheme = self.scheme(title, status=status, highlights='- big money', contact_details='- Helpline 1800',
                             overview=[{'label': 'Mode', 'value': 'Online'}],
                             links=[{'kind': 'website', 'label': 'Portal', 'url': 'https://portal.example/'}],
                             additional_sections=[{'heading': 'Selection Process', 'text': '- Committee'}], **extra)
        scheme.set_tags([{'group': 'scheme_type', 'name': 'Pension'}, {'group': 'person_type', 'name': 'Labour'}])
        return scheme

    def test_detail_returns_every_captured_field(self) -> None:
        scheme = self.rich()
        data = self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']
        self.assertEqual(data['highlights'], '- big money')
        self.assertEqual(data['contactDetails'], '- Helpline 1800')
        self.assertEqual(data['overview'], [{'label': 'Mode', 'value': 'Online'}])
        self.assertEqual(data['links'][0]['url'], 'https://portal.example/')
        self.assertEqual(data['additionalSections'][0]['heading'], 'Selection Process')
        self.assertEqual(sorted((t['group'], t['name']) for t in data['tags']), [('person_type', 'Labour'), ('scheme_type', 'Pension')])

    def test_list_rows_carry_tags_without_extra_queries_per_row(self) -> None:
        for index in range(5):
            self.rich(f'Rich {index}')
        client = self.as_user(self.member())
        rows = client.get('/schemes/get_all/').data['data']['data']
        self.assertEqual(len(rows[0]['tags']), 2)
        with self.assertNumQueries(4):  # count, one page query, one prefetch for ALL tags, one for ALL images
            client.get('/schemes/get_all/')
        sql = ' '.join(q['sql'] for q in self.captured_queries(client))
        self.assertNotIn('"additional_sections"', sql)  # heavy detail columns are not loaded for the list

    @staticmethod
    def captured_queries(client: APIClient):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as context:
            client.get('/schemes/get_all/')
        return context.captured_queries

    def test_filter_by_tag_groups(self) -> None:
        pension = self.rich('Pension one')
        other = self.scheme('Other one')
        other.set_tags([{'group': 'scheme_type', 'name': 'Health'}, {'group': 'caste', 'name': 'SC'}])
        client = self.as_user(self.member())

        def ids(query: str) -> list[int]:
            return [r['schemeId'] for r in client.get(f'/schemes/get_all/?{query}').data['data']['data']]

        self.assertEqual(ids('filter_key=schemeType&filter_value=Pension'), [pension.scheme_id])
        self.assertEqual(ids('filter_key=personType&filter_value=Labour'), [pension.scheme_id])
        self.assertEqual(ids('filter_key=caste&filter_value=SC'), [other.scheme_id])
        self.assertEqual(ids('filter_key=schemeType&filter_value=Nothing'), [])
        self.assertEqual(ids('filter_key=personType&filter_value=Pension'), [])  # right name, wrong group

    def test_tag_filter_never_leaks_unpublished_schemes(self) -> None:
        self.rich('Hidden one', status='pending_review')
        rows = self.as_user(self.member()).get('/schemes/get_all/?filter_key=schemeType&filter_value=Pension').data['data']['data']
        self.assertEqual(rows, [])

    def test_tag_listing_counts_only_published_and_filters_by_group(self) -> None:
        self.rich('One')
        self.rich('Two')
        self.rich('Hidden', status='unpublished')
        client = self.as_user(self.member())
        data = client.get('/schemes/tag/get_all/').data['data']['data']
        self.assertEqual(data, [{'group': 'person_type', 'name': 'Labour', 'count': 2}, {'group': 'scheme_type', 'name': 'Pension', 'count': 2}])
        only = client.get('/schemes/tag/get_all/?group=person_type').data['data']['data']
        self.assertEqual([t['group'] for t in only], ['person_type'])
        self.assertEqual(client.get('/schemes/tag/get_all/?group=bogus').status_code, 400)

    def test_tag_listing_permissions(self) -> None:
        self.assertEqual(self.as_user(None).get('/schemes/tag/get_all/').status_code, 401)
        self.assertEqual(self.as_user(self.staff('Scheme Reviewers')).get('/schemes/tag/get_all/').status_code, 403)

    def test_search_covers_highlights_but_not_internal_columns(self) -> None:
        self.rich('Searchable', content_hash='deadbeefcafe1234')
        client = self.as_user(self.member())
        self.assertEqual(len(client.get('/schemes/get_all/?search_key=big money').data['data']['data']), 1)
        self.assertEqual(client.get('/schemes/get_all/?search_key=deadbeefcafe1234').data['data']['data'], [])

    def test_stored_links_are_returned_exactly_as_validated_data(self) -> None:
        scheme = self.rich()
        data = self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']
        self.assertTrue(all(l['url'].startswith(('http://', 'https://')) for l in data['links']))


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SchemeAdminRichTests(SchemeApiBase):
    LIST = '/admin/schemes/scheme/'

    def setUp(self) -> None:
        super().setUp()
        self.reviewer = self.staff('Scheme Reviewers')
        self.client_ = Client()
        self.client_.force_login(self.reviewer)

    def form(self, scheme: Scheme, **overrides) -> dict:
        data = {
            'title': scheme.title, 'department': scheme.department, 'description': scheme.description, 'eligibility': scheme.eligibility,
            'benefits': scheme.benefits, 'application_procedure': scheme.application_procedure, 'required_documents': scheme.required_documents,
            'highlights': scheme.highlights, 'contact_details': scheme.contact_details,
            'links_text': '', 'overview_text': '', 'additional_text': '[]', 'source_url': '', '_save': 'Save', 'is_accepting_applications': 'on',
            'tags-TOTAL_FORMS': '0', 'tags-INITIAL_FORMS': '0', 'tags-MIN_NUM_FORMS': '0', 'tags-MAX_NUM_FORMS': '1000',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0', 'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '10', 'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0', 'documents-MIN_NUM_FORMS': '0', 'documents-MAX_NUM_FORMS': '10',
        }
        data.update(overrides)
        return data

    def post(self, scheme: Scheme, **overrides):
        return self.client_.post(f'{self.LIST}{scheme.pk}/change/', self.form(scheme, **overrides), follow=True)

    def test_page_renders_with_the_new_editors(self) -> None:
        scheme = self.scheme('Imported one')
        scheme.set_tags([{'group': 'caste', 'name': 'SC'}])
        page_ = self.client_.get(f'{self.LIST}{scheme.pk}/change/')
        self.assertEqual(page_.status_code, 200)
        for needle in ('links_text', 'overview_text', 'additional_text', 'contact_details', 'highlights', 'tags-0-name'):
            self.assertContains(page_, needle)

    def test_valid_edits_are_saved_and_protect_the_scheme(self) -> None:
        scheme = self.scheme('Imported one')
        self.post(
            scheme, links_text='website | Portal | https://portal.example/\nlink | Guide | https://portal.example/g.pdf',
            overview_text='Mode | Online\nFee | None', additional_text='[{"heading": "Extra", "text": "More info"}]',
            highlights='- new', contact_details='- 1800',
        )
        scheme.refresh_from_db()
        self.assertEqual([l['kind'] for l in scheme.links], ['website', 'link'])
        self.assertEqual(scheme.overview, [{'label': 'Mode', 'value': 'Online'}, {'label': 'Fee', 'value': 'None'}])
        self.assertEqual(scheme.additional_sections, [{'heading': 'Extra', 'text': 'More info'}])
        self.assertEqual((scheme.highlights, scheme.contact_details, scheme.locally_edited), ('- new', '- 1800', True))

    def test_invalid_structured_input_is_rejected_and_nothing_changes(self) -> None:
        scheme = self.scheme('Imported one')
        bad_inputs = (
            {'links_text': 'link | x | javascript:alert(1)'}, {'links_text': 'link | x | data:text/html,hi'}, {'links_text': 'nokind | x | https://a.example'},
            {'links_text': 'just text'}, {'links_text': 'link | x | https://a.example/has space'},
            {'links_text': '\n'.join(f'link | L{i} | https://a.example/{i}' for i in range(31))},
            {'overview_text': 'no separator'}, {'overview_text': ' | value only'},
            {'additional_text': 'not json'}, {'additional_text': '{"heading": "x"}'}, {'additional_text': '[{"heading": 1, "text": "x"}]'},
            {'additional_text': '[{"heading": "x"}]'}, {'additional_text': '5'}, {'additional_text': '"text"'}, {'additional_text': 'null'},
            {'additional_text': '[' + ','.join(['{"heading": "h", "text": "t"}'] * 41) + ']'},
            {'overview_text': '\n'.join(f'L{i} | v' for i in range(31))},
        )
        for bad in bad_inputs:
            self.post(scheme, **bad)
        scheme.refresh_from_db()
        self.assertEqual((scheme.links, scheme.overview, scheme.additional_sections, scheme.locally_edited), ([], [], [], False))

    def test_saving_without_changes_does_not_flag_the_scheme(self) -> None:
        scheme = self.scheme('Imported one')
        self.post(scheme)
        scheme.refresh_from_db()
        self.assertFalse(scheme.locally_edited)

    def test_tag_inline_edit_saves_and_protects_the_scheme(self) -> None:
        scheme = self.scheme('Imported one')
        self.post(scheme, **{'tags-TOTAL_FORMS': '1', 'tags-0-group': 'scheme_type', 'tags-0-name': 'Pension', 'tags-0-scheme': scheme.pk})
        scheme.refresh_from_db()
        self.assertEqual(list(scheme.tags.values_list('group', 'name')), [('scheme_type', 'Pension')])
        self.assertTrue(scheme.locally_edited)

    def test_manual_add_with_all_new_fields(self) -> None:
        data = {
            'title': 'Hand made', 'department': 'D', 'description': 'desc', 'eligibility': '', 'benefits': '', 'application_procedure': '',
            'required_documents': '', 'highlights': '- hl', 'contact_details': '- c', 'source_url': '',
            'links_text': 'website | Portal | https://portal.example/', 'overview_text': 'Mode | Online', 'additional_text': '[{"heading": "H", "text": "T"}]',
            'tags-TOTAL_FORMS': '1', 'tags-INITIAL_FORMS': '0', 'tags-MIN_NUM_FORMS': '0', 'tags-MAX_NUM_FORMS': '1000',
            'tags-0-group': 'person_type', 'tags-0-name': 'Farmer', '_save': 'Save', 'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0', 'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '10', 'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0', 'documents-MIN_NUM_FORMS': '0', 'documents-MAX_NUM_FORMS': '10',
        }
        self.client_.post(self.LIST + 'add/', data, follow=True)
        scheme = Scheme.objects.get(title='Hand made')
        self.assertEqual((scheme.is_manual, scheme.links[0]['label'], scheme.additional_sections[0]['heading']), (True, 'Portal', 'H'))
        self.assertEqual(list(scheme.tags.values_list('group', 'name')), [('person_type', 'Farmer')])

    def test_scheme_reviewers_group_includes_tag_permissions(self) -> None:
        codes = set(Group.objects.get(name='Scheme Reviewers').permissions.values_list('codename', flat=True))
        self.assertTrue({'view_schemetag', 'add_schemetag', 'change_schemetag', 'delete_schemetag'} <= codes)


# ======================================================================== self-hosted images

IMG_A = f'{HOST}/sites/default/files/2024-01/a.jpg'
IMG_B = f'{HOST}/sites/default/files/2024-01/b.png'


def media_path(image: SchemeImage) -> Path:
    return Path(django_settings.MEDIA_ROOT) / image.file.name


class ImageSniffTests(TestCase):
    def test_real_image_signatures_are_recognised_from_bytes(self) -> None:
        self.assertEqual(sniff_image_extension(JPG), 'jpg')
        self.assertEqual(sniff_image_extension(PNG), 'png')
        self.assertEqual(sniff_image_extension(GIF), 'gif')
        self.assertEqual(sniff_image_extension(WEBP), 'webp')
        self.assertEqual(sniff_image_extension(b'GIF87a' + b'0' * 8), 'gif')

    def test_everything_else_is_refused(self) -> None:
        for bad in (SVG, HTML_BYTES, b'', b'\xff', b'PK\x03\x04zip', b'%PDF-1.4', b'RIFF\x00\x00\x00\x00WAVEfmt ', b'MZ\x90\x00 executable'):
            self.assertIsNone(sniff_image_extension(bad), bad[:12])


class SourceImageFetchTests(TestCase):
    def setUp(self) -> None:
        sleeper = mock.patch.object(source_module.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_only_the_approved_host_and_upload_folder(self) -> None:
        opener = _Opener(_Response(PNG))
        source = SchemeSource(opener=opener)
        self.assertEqual(source.fetch_image(IMG_A), PNG)
        for bad in ('https://evil.example/sites/default/files/a.jpg', f'{HOST}/themes/custom/logo.png', f'{HOST}/node/1',
                    'http://www.govtschemes.in/sites/default/files/a.jpg'):
            with self.assertRaises(SourceError, msg=bad):
                source.fetch_image(bad)
        self.assertEqual(len(opener.calls), 1)

    def test_size_cap_comes_from_configuration(self) -> None:
        with mock.patch.object(Configurations, 'scheme_image_max_bytes', 100):
            with self.assertRaises(SourceError):
                SchemeSource(opener=_Opener(_Response(b'x' * 101))).fetch_image(IMG_A)
            self.assertEqual(SchemeSource(opener=_Opener(_Response(b'x' * 100))).fetch_image(IMG_A), b'x' * 100)


class SyncImageTests(SyncBase):
    def page_with(self, *urls: str, title: str = 'Pic') -> str:
        return page(title, images=tuple(u.replace(HOST, '') for u in urls))

    def sync(self, *urls: str, lastmod: str = '2024-05-01', **source_kwargs):
        source = FakeSource(sitemap((url('pic-scheme'), lastmod)), {url('pic-scheme'): self.page_with(*urls)}, **source_kwargs)
        return source, self.run_sync(source)

    def test_images_are_downloaded_into_our_own_storage(self) -> None:
        source, run = self.sync(IMG_A, IMG_B)
        scheme = Scheme.objects.get()
        images = list(scheme.images.all())
        self.assertEqual((run.images_downloaded, run.status, len(images)), (2, 'success', 2))
        self.assertEqual([i.position for i in images], [0, 1])
        self.assertEqual([i.source_url for i in images], [IMG_A, IMG_B])
        for image in images:
            self.assertTrue(media_path(image).is_file())
            self.assertEqual(media_path(image).read_bytes(), png(image.source_url))
            self.assertTrue(image.file.name.startswith(f'schemes/{scheme.pk}/'))
            self.assertNotIn('govtschemes', image.file.url)
            self.assertNotIn('a.jpg', image.file.name)

    def test_file_type_and_name_come_from_content_not_from_the_url(self) -> None:
        self.sync(IMG_A, IMG_B, images={IMG_A: PNG + b'x', IMG_B: JPG + b'y'})
        names = [i.file.name.rsplit('.', 1)[1] for i in Scheme.objects.get().images.all()]
        self.assertEqual(names, ['png', 'jpg'])

    def test_second_run_downloads_nothing_again(self) -> None:
        source, _ = self.sync(IMG_A, IMG_B)
        source.fetched_images.clear()
        source2, run = self.sync(IMG_A, IMG_B, lastmod='2024-06-01')
        self.assertEqual((source2.fetched_images, run.images_downloaded, Scheme.objects.get().images.count()), ([], 0, 2))

    def test_new_image_is_added_and_removed_image_is_deleted_with_its_file(self) -> None:
        self.sync(IMG_A, IMG_B)
        gone = Scheme.objects.get().images.get(source_url=IMG_B)
        gone_path = media_path(gone)
        third = f'{HOST}/sites/default/files/2024-01/c.gif'
        source, run = self.sync(IMG_A, third, lastmod='2024-06-01')
        self.assertEqual(source.fetched_images, [third])
        self.assertEqual(list(Scheme.objects.get().images.values_list('source_url', flat=True)), [IMG_A, third])
        self.assertFalse(gone_path.exists())

    def test_positions_follow_the_page_order(self) -> None:
        self.sync(IMG_A, IMG_B)
        self.sync(IMG_B, IMG_A, lastmod='2024-06-01')
        self.assertEqual(list(Scheme.objects.get().images.order_by('position').values_list('source_url', flat=True)), [IMG_B, IMG_A])

    def test_failed_download_keeps_the_scheme_and_retries_next_run(self) -> None:
        _, run = self.sync(IMG_A, IMG_B, images={IMG_A: SourceError('HTTP 500')})
        scheme = Scheme.objects.get()
        self.assertEqual((run.status, run.errors, scheme.images.count(), scheme.media_synced_at), ('partial', 1, 1, None))
        self.assertIsNotNone(scheme.source_lastmod)  # the page itself is up to date; only the media is unverified
        self.assertIn(IMG_A, run.error_summary)
        source, run2 = self.sync(IMG_A, IMG_B)  # source is healthy again; lastmod is unchanged upstream
        scheme.refresh_from_db()
        self.assertEqual((run2.status, run2.images_downloaded, scheme.images.count()), ('success', 1, 2))
        self.assertEqual(source.fetched_images, [IMG_A])
        self.assertIsNotNone(scheme.media_synced_at)

    def test_non_images_are_never_stored(self) -> None:
        _, run = self.sync(IMG_A, IMG_B, images={IMG_A: HTML_BYTES, IMG_B: SVG})
        self.assertEqual((run.status, run.errors, Scheme.objects.get().images.count()), ('partial', 2, 0))
        self.assertFalse((Path(django_settings.MEDIA_ROOT) / 'schemes').exists() and any((Path(django_settings.MEDIA_ROOT) / 'schemes').rglob('*.*')))

    def test_same_picture_under_two_urls_is_stored_once(self) -> None:
        _, run = self.sync(IMG_A, IMG_B, images={IMG_A: PNG, IMG_B: PNG})
        self.assertEqual((run.errors, Scheme.objects.get().images.count(), run.images_downloaded), (0, 1, 1))

    def test_admin_owned_scheme_images_are_not_touched_by_the_sync(self) -> None:
        self.sync(IMG_A)
        scheme = Scheme.objects.get()
        Scheme.objects.filter(pk=scheme.pk).update(locally_edited=True)
        source, _ = self.sync(IMG_A, IMG_B, lastmod='2024-06-01')
        self.assertEqual((source.fetched_images, scheme.images.count()), ([], 1))

    def test_pictures_uploaded_by_admins_survive_a_sync(self) -> None:
        self.sync(IMG_A)
        scheme = Scheme.objects.get()
        mine = SchemeImage.objects.create(scheme=scheme, file=ContentFile(png('mine'), name='x'), position=5)
        self.sync(IMG_B, lastmod='2024-06-01')
        self.assertTrue(SchemeImage.objects.filter(pk=mine.pk).exists())
        self.assertTrue(media_path(mine).is_file())
        self.assertEqual(list(scheme.images.exclude(source_url=None).values_list('source_url', flat=True)), [IMG_B])

    def test_manual_scheme_with_the_same_url_gets_no_downloads(self) -> None:
        Scheme.objects.create(title='Mine', source_url=url('pic-scheme'), is_manual=True, description='x')
        source, _ = self.sync(IMG_A)
        self.assertEqual((source.fetched_images, SchemeImage.objects.count()), ([], 0))

    def test_robots_blocked_image_is_skipped_without_error(self) -> None:
        source, run = self.sync(IMG_A, IMG_B, blocked=(IMG_A,))
        self.assertEqual((source.fetched_images, run.errors, Scheme.objects.get().images.count()), ([IMG_B], 0, 1))

    def test_polite_delay_applies_to_image_requests_too(self) -> None:
        with mock.patch.object(Configurations, 'scheme_sync_delay_seconds', 1.5):
            self.sync(IMG_A, IMG_B)
        self.assertEqual(self.sleeps, [1.5, 1.5])

    def test_at_most_five_images_per_scheme(self) -> None:
        many = [f'{HOST}/sites/default/files/2024-01/p{i}.jpg' for i in range(9)]
        source, _ = self.sync(*many)
        self.assertEqual((len(source.fetched_images), Scheme.objects.get().images.count()), (5, 5))

    def test_files_disappear_with_the_row_and_with_the_scheme(self) -> None:
        self.sync(IMG_A, IMG_B)
        scheme = Scheme.objects.get()
        first, second = list(scheme.images.all())
        first_path, second_path = media_path(first), media_path(second)
        first.delete()
        self.assertFalse(first_path.exists())
        self.assertTrue(second_path.exists())
        admin = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        Scheme.remove(scheme.pk, admin)
        self.assertFalse(second_path.exists())

    def test_deleting_a_scheme_in_bulk_removes_all_its_files(self) -> None:
        self.sync(IMG_A, IMG_B)
        paths = [media_path(i) for i in SchemeImage.objects.all()]
        Scheme.objects.all().delete()
        self.assertFalse(any(p.exists() for p in paths))


class SchemeImageApiTests(SchemeApiBase):
    def with_images(self, title: str = 'Pictured', **extra) -> Scheme:
        scheme = self.scheme(title, **extra)
        self.add_image(scheme, 'second', position=1, source_url=f'{HOST}/sites/default/files/b.png')
        self.add_image(scheme, 'first', position=0, source_url=f'{HOST}/sites/default/files/a.png')
        return scheme

    def test_images_are_absolute_urls_on_our_own_server_in_position_order(self) -> None:
        scheme = self.with_images()
        client = self.as_user(self.member())
        detail = client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']['images']
        urls = [f'http://testserver{i.file.url}' for i in scheme.images.all()]
        self.assertEqual(detail, urls)
        self.assertTrue(all(u.startswith('http://testserver/media/schemes/') for u in detail))
        listed = client.get('/schemes/get_all/').data['data']['data'][0]['imageUrl']
        self.assertEqual(listed, urls[0])

    def test_public_media_base_url_can_be_configured(self) -> None:
        scheme = self.with_images()
        with mock.patch.object(Configurations, 'media_base_url', 'https://cdn.example.com/'):
            data = self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']
        self.assertTrue(all(u.startswith('https://cdn.example.com/media/schemes/') for u in data['images']))

    def test_nothing_that_names_the_source_site_is_ever_returned(self) -> None:
        scheme = self.with_images(
            links=[
                {'kind': 'website', 'label': 'Official', 'url': 'https://saralharyana.gov.in/'},
                {'kind': 'brochure', 'label': 'Brochure', 'url': f'{HOST}/sites/default/files/2024-02/brochure.pdf'},
                {'kind': 'link', 'label': 'Mirror', 'url': 'https://WWW.GOVTSCHEMES.IN/other'},
            ],
            additional_sections=[], contact_details='- call 1800',
        )
        client = self.as_user(self.member())
        detail = client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}')
        listing = client.get('/schemes/get_all/')
        for response in (detail, listing):
            self.assertNotIn('govtschemes', str(response.data).lower())
        self.assertEqual([l['url'] for l in detail.data['data']['links']], ['https://saralharyana.gov.in/'])

    def test_source_url_is_not_returned_but_is_still_stored(self) -> None:
        scheme = self.with_images()
        client = self.as_user(self.member())
        detail = client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']
        row = client.get('/schemes/get_all/').data['data']['data'][0]
        self.assertNotIn('sourceUrl', detail)
        self.assertNotIn('sourceUrl', row)
        self.assertEqual(Scheme.objects.get(pk=scheme.pk).source_url, url('pictured'))

    def test_no_pictures_means_null_and_empty_list(self) -> None:
        scheme = self.scheme('Plain')
        client = self.as_user(self.member())
        self.assertIsNone(client.get('/schemes/get_all/').data['data']['data'][0]['imageUrl'])
        self.assertEqual(client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}').data['data']['images'], [])

    def test_list_stays_at_four_queries_with_many_pictures(self) -> None:
        for index in range(5):
            self.with_images(f'Pictured {index}')
        client = self.as_user(self.member())
        with self.assertNumQueries(4):  # count, page, all tags, all pictures: independent of the number of rows
            client.get('/schemes/get_all/')

    def test_unpublished_scheme_pictures_are_not_exposed(self) -> None:
        scheme = self.with_images('Hidden', status='pending_review')
        self.assertEqual(self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}').status_code, 404)
        self.assertEqual(self.as_user(self.member()).get('/schemes/get_all/').data['data']['data'], [])


class SchemeImageAdminTests(SchemeApiBase):
    LIST = '/admin/schemes/scheme/'

    def setUp(self) -> None:
        super().setUp()
        self.reviewer = self.staff('Scheme Reviewers')
        self.client_ = Client()
        self.client_.force_login(self.reviewer)

    def payload(self, scheme: Scheme | None = None, files: tuple[tuple[str, bytes], ...] = (), **overrides) -> dict:
        data = {
            'title': scheme.title if scheme else 'Hand made', 'department': '', 'description': scheme.description if scheme else 'desc',
            'eligibility': scheme.eligibility if scheme else '', 'benefits': scheme.benefits if scheme else '',
            'application_procedure': scheme.application_procedure if scheme else '', 'required_documents': scheme.required_documents if scheme else '',
            'highlights': '', 'contact_details': '', 'links_text': '', 'overview_text': '', 'additional_text': '[]', 'source_url': '', '_save': 'Save',
            'tags-TOTAL_FORMS': '0', 'tags-INITIAL_FORMS': '0', 'tags-MIN_NUM_FORMS': '0', 'tags-MAX_NUM_FORMS': '1000',
            'images-TOTAL_FORMS': str(len(files)), 'images-INITIAL_FORMS': '0', 'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '10', 'documents-TOTAL_FORMS': '0', 'documents-INITIAL_FORMS': '0', 'documents-MIN_NUM_FORMS': '0', 'documents-MAX_NUM_FORMS': '10',
        }
        for index, (name, content) in enumerate(files):
            data[f'images-{index}-file'] = SimpleUploadedFile(name, content)
            data[f'images-{index}-position'] = str(index)
        data.update(overrides)
        return data

    def add(self, **kwargs):
        return self.client_.post(self.LIST + 'add/', self.payload(**kwargs), follow=True)

    def edit(self, scheme: Scheme, **kwargs):
        return self.client_.post(f'{self.LIST}{scheme.pk}/change/', self.payload(scheme, **kwargs), follow=True)

    def test_upload_for_a_manual_scheme_is_stored_under_a_name_made_from_its_content(self) -> None:
        self.add(files=(('photo.html', PNG + b'upload'),))
        scheme = Scheme.objects.get(title='Hand made')
        image = scheme.images.get()
        self.assertTrue(media_path(image).is_file())
        self.assertRegex(image.file.name, rf'^schemes/{scheme.pk}/[0-9a-f]{{24}}\.png$')
        self.assertIsNone(image.source_url)
        self.assertEqual(len(image.sha256), 64)

    def test_all_four_image_types_are_accepted(self) -> None:
        self.add(files=(('a.dat', JPG), ('b.dat', PNG + b'1'), ('c.dat', GIF), ('d.dat', WEBP)))
        extensions = sorted(i.file.name.rsplit('.', 1)[1] for i in Scheme.objects.get(title='Hand made').images.all())
        self.assertEqual(extensions, ['gif', 'jpg', 'png', 'webp'])

    def test_html_svg_and_disguised_files_are_rejected(self) -> None:
        for name, content in (('x.jpg', HTML_BYTES), ('x.svg', SVG), ('x.png', b'not an image at all'), ('x.jpg', b'')):
            self.add(files=((name, content),))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())
        self.assertEqual(SchemeImage.objects.count(), 0)

    def test_oversized_upload_is_rejected(self) -> None:
        with mock.patch.object(Configurations, 'scheme_image_max_bytes', 50):
            self.add(files=(('big.png', PNG + b'x' * 100),))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())

    def test_the_same_picture_twice_is_attached_once(self) -> None:
        self.add(files=(('a.png', PNG + b'same'), ('b.png', PNG + b'same')))
        self.assertEqual(Scheme.objects.get(title='Hand made').images.count(), 1)

    def test_uploading_to_an_imported_scheme_protects_it_from_the_sync(self) -> None:
        scheme = self.scheme('Imported one')
        self.edit(scheme, files=(('mine.png', PNG + b'mine'),))
        scheme.refresh_from_db()
        self.assertEqual((scheme.images.count(), scheme.locally_edited), (1, True))

    def test_removing_a_picture_in_the_admin_deletes_its_file(self) -> None:
        scheme = self.scheme('Imported one')
        image = self.add_image(scheme)
        path = media_path(image)
        self.edit(scheme, **{'images-TOTAL_FORMS': '1', 'images-INITIAL_FORMS': '1', 'images-0-image_id': image.pk,
                             'images-0-scheme': scheme.pk, 'images-0-position': '0', 'images-0-DELETE': 'on'})
        self.assertFalse(SchemeImage.objects.exists())
        self.assertFalse(path.exists())

    def test_at_most_ten_pictures(self) -> None:
        self.add(files=tuple((f'{i}.png', PNG + str(i).encode()) for i in range(11)))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())

    def test_the_admin_page_offers_upload_not_url_text(self) -> None:
        scheme = self.scheme('Imported one')
        page_ = self.client_.get(f'{self.LIST}{scheme.pk}/change/')
        self.assertContains(page_, 'images-0-file')
        self.assertNotContains(page_, 'images_text')

    def test_reviewers_may_manage_scheme_images(self) -> None:
        codes = set(Group.objects.get(name='Scheme Reviewers').permissions.values_list('codename', flat=True))
        self.assertTrue({'view_schemeimage', 'add_schemeimage', 'change_schemeimage', 'delete_schemeimage'} <= codes)

    def test_other_staff_cannot_upload(self) -> None:
        scheme = self.scheme('Imported one')
        other = Client()
        other.force_login(self.staff('Member Managers'))
        other.post(f'{self.LIST}{scheme.pk}/change/', self.payload(scheme, files=(('x.png', PNG + b'z'),)))
        self.assertEqual(SchemeImage.objects.count(), 0)


# ======================================================================== self-hosted PDF documents

DOC_A = f'{HOST}/sites/default/files/2022-05/Amma%20Guide.pdf'
DOC_B = f'{HOST}/sites/default/files/2022-06/rules.pdf'


def doc_path(document: SchemeDocument) -> Path:
    return Path(django_settings.MEDIA_ROOT) / document.file.name


class PdfSniffTests(TestCase):
    def test_signature_decides_not_name(self) -> None:
        self.assertTrue(looks_like_pdf(b'%PDF-1.7 rest'))
        self.assertTrue(looks_like_pdf(PDF))
        for bad in (b'', b'%PDX-1.4', b' %PDF-1.4', HTML_BYTES, PNG, JPG, SVG, b'PK\x03\x04zip', b'MZ\x90\x00'):
            self.assertFalse(looks_like_pdf(bad), bad[:10])


class SourceDocumentFetchTests(TestCase):
    def setUp(self) -> None:
        sleeper = mock.patch.object(source_module.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_only_pdfs_in_the_upload_folder_of_the_approved_host(self) -> None:
        opener = _Opener(_Response(PDF), _Response(PDF))
        source = SchemeSource(opener=opener)
        self.assertEqual(source.fetch_document(DOC_A), PDF)
        self.assertEqual(source.fetch_document(f'{HOST}/sites/default/files/2022/UPPER.PDF'), PDF)
        for bad in (f'{HOST}/sites/default/files/2022/file.docx', f'{HOST}/sites/default/files/2022/file.pdf.exe', f'{HOST}/themes/guide.pdf',
                    'https://evil.example/sites/default/files/a.pdf', 'http://www.govtschemes.in/sites/default/files/a.pdf', f'{HOST}/sites/default/files/'):
            with self.assertRaises(SourceError, msg=bad):
                source.fetch_document(bad)
        self.assertEqual(len(opener.calls), 2)

    def test_document_size_cap_comes_from_configuration(self) -> None:
        with mock.patch.object(Configurations, 'scheme_document_max_bytes', 100):
            with self.assertRaises(SourceError):
                SchemeSource(opener=_Opener(_Response(b'x' * 101))).fetch_document(DOC_A)
            self.assertEqual(SchemeSource(opener=_Opener(_Response(b'x' * 100))).fetch_document(DOC_A), b'x' * 100)


class SyncDocumentTests(SyncBase):
    @staticmethod
    def doc_page(brochure: str | None = '/sites/default/files/2022-05/Amma%20Guide.pdf', links: tuple[tuple[str, str], ...] = (('Guidelines', DOC_B),),
                 title: str = 'Doc') -> str:
        return page(title, images=(), links=links, brochure=('Brochure', brochure) if brochure else None)

    def sync(self, html: str | None = None, lastmod: str = '2024-05-01', **source_kwargs):
        source = FakeSource(sitemap((url('doc-scheme'), lastmod)), {url('doc-scheme'): html or self.doc_page()}, **source_kwargs)
        return source, self.run_sync(source)

    def test_pdfs_are_mirrored_into_our_own_storage(self) -> None:
        source, run = self.sync()
        scheme = Scheme.objects.get()
        documents = list(scheme.documents.all())
        self.assertEqual((run.documents_downloaded, run.status, len(documents)), (2, 'success', 2))
        self.assertEqual([(d.kind, d.label, d.position) for d in documents], [('brochure', 'Brochure', 0), ('document', 'Guidelines', 1)])
        self.assertEqual([d.source_url for d in documents], [DOC_A, DOC_B])
        for document in documents:
            self.assertEqual(doc_path(document).read_bytes(), pdf(document.source_url))
            self.assertRegex(document.file.name, rf'^schemes/{scheme.pk}/docs/[0-9a-f]{{24}}\.pdf$')
            self.assertEqual(document.size_bytes, len(pdf(document.source_url)))
            self.assertNotIn('govtschemes', document.file.url)

    def test_the_same_file_linked_under_two_spellings_is_fetched_and_stored_once(self) -> None:
        html = self.doc_page(links=(('Same guide again', f'{HOST}/sites/default/files/2022-05/AMMA%20GUIDE.pdf'),))
        source, run = self.sync(html)
        self.assertEqual((source.fetched_documents, run.documents_downloaded, Scheme.objects.get().documents.count()), ([DOC_A], 1, 1))
        self.assertEqual(Scheme.objects.get().documents.get().kind, 'brochure')

    def test_identical_content_under_different_paths_is_stored_once(self) -> None:
        _, run = self.sync(documents={DOC_A: PDF, DOC_B: PDF})
        self.assertEqual((run.errors, run.documents_downloaded, Scheme.objects.get().documents.count()), (0, 1, 1))

    def test_second_run_downloads_nothing_again(self) -> None:
        self.sync()
        source, run = self.sync(lastmod='2024-06-01')
        self.assertEqual((source.fetched_documents, run.documents_downloaded, Scheme.objects.get().documents.count()), ([], 0, 2))

    def test_new_document_is_added_and_removed_one_is_deleted_with_its_file(self) -> None:
        self.sync()
        gone = Scheme.objects.get().documents.get(source_url=DOC_B)
        gone_path = doc_path(gone)
        third = f'{HOST}/sites/default/files/2022-07/forms.pdf'
        source, _ = self.sync(self.doc_page(links=(('Forms', third),)), lastmod='2024-06-01')
        self.assertEqual(source.fetched_documents, [third])
        self.assertEqual(list(Scheme.objects.get().documents.values_list('source_url', flat=True)), [DOC_A, third])
        self.assertFalse(gone_path.exists())

    def test_label_kind_and_order_are_refreshed_without_downloading(self) -> None:
        self.sync()
        html = self.doc_page(brochure=None, links=(('Rules (new title)', DOC_B), ('Guide (now a plain document)', DOC_A)))
        source, _ = self.sync(html, lastmod='2024-06-01')
        rows = list(Scheme.objects.get().documents.order_by('position').values_list('source_url', 'label', 'kind'))
        self.assertEqual(rows, [(DOC_B, 'Rules (new title)', 'document'), (DOC_A, 'Guide (now a plain document)', 'document')])
        self.assertEqual(source.fetched_documents, [])

    def test_failed_download_keeps_the_scheme_and_retries_next_run(self) -> None:
        _, run = self.sync(documents={DOC_A: SourceError('HTTP 500')})
        scheme = Scheme.objects.get()
        self.assertEqual((run.status, run.errors, scheme.documents.count(), scheme.media_synced_at), ('partial', 1, 1, None))
        self.assertIsNotNone(scheme.source_lastmod)
        source, run2 = self.sync()
        scheme.refresh_from_db()
        self.assertEqual((run2.status, run2.documents_downloaded, scheme.documents.count(), source.fetched_documents), ('success', 1, 2, [DOC_A]))
        self.assertIsNotNone(scheme.media_synced_at)

    def test_files_that_are_not_pdfs_are_never_stored(self) -> None:
        _, run = self.sync(documents={DOC_A: HTML_BYTES, DOC_B: PNG})
        self.assertEqual((run.status, run.errors, Scheme.objects.get().documents.count()), ('partial', 2, 0))

    def test_only_source_hosted_pdfs_are_downloaded(self) -> None:
        html = self.doc_page(links=(
            ('External PDF', 'https://portal.example/guide.pdf'), ('Word file', f'{HOST}/sites/default/files/2022/form.docx'),
            ('Page', f'{HOST}/some-other-scheme'), ('Mine', DOC_B),
        ))
        source, _ = self.sync(html)
        self.assertEqual(source.fetched_documents, [DOC_A, DOC_B])
        stored_links = Scheme.objects.get().links
        self.assertIn('https://portal.example/guide.pdf', [l['url'] for l in stored_links])  # external official links stay as links

    def test_admin_owned_scheme_documents_are_not_touched_by_the_sync(self) -> None:
        self.sync()
        Scheme.objects.update(locally_edited=True)
        source, _ = self.sync(self.doc_page(links=(('New', f'{HOST}/sites/default/files/2022-08/new.pdf'),)), lastmod='2024-06-01')
        self.assertEqual((source.fetched_documents, Scheme.objects.get().documents.count()), ([], 2))

    def test_documents_uploaded_by_admins_survive_a_sync(self) -> None:
        self.sync()
        scheme = Scheme.objects.get()
        mine = SchemeDocument.objects.create(scheme=scheme, file=ContentFile(pdf('mine'), name='x'), label='Mine', position=9)
        self.sync(self.doc_page(brochure=None, links=()), lastmod='2024-06-01')
        self.assertEqual(list(scheme.documents.values_list('pk', flat=True)), [mine.pk])
        self.assertTrue(doc_path(mine).is_file())

    def test_manual_scheme_with_the_same_url_gets_no_downloads(self) -> None:
        Scheme.objects.create(title='Mine', source_url=url('doc-scheme'), is_manual=True, description='x')
        source, _ = self.sync()
        self.assertEqual((source.fetched_documents, SchemeDocument.objects.count()), ([], 0))

    def test_robots_blocked_document_is_skipped_without_error(self) -> None:
        source, run = self.sync(blocked=(DOC_A,))
        self.assertEqual((source.fetched_documents, run.errors, Scheme.objects.get().documents.count()), ([DOC_B], 0, 1))

    def test_polite_delay_applies_to_document_requests_too(self) -> None:
        with mock.patch.object(Configurations, 'scheme_sync_delay_seconds', 1.5):
            self.sync()
        self.assertEqual(self.sleeps, [1.5, 1.5])

    def test_at_most_ten_documents_per_scheme(self) -> None:
        many = tuple((f'Doc {i}', f'{HOST}/sites/default/files/2022/d{i}.pdf') for i in range(15))
        source, _ = self.sync(self.doc_page(brochure=None, links=many))
        self.assertEqual((len(source.fetched_documents), Scheme.objects.get().documents.count()), (10, 10))

    def test_pictures_and_documents_sync_together(self) -> None:
        html = page('Both', images=('/sites/default/files/2024-01/a.jpg',), links=(('Guide', DOC_B),))
        source, run = self.sync(html)
        self.assertEqual((run.images_downloaded, run.documents_downloaded, run.status), (1, 1, 'success'))

    def test_files_disappear_with_the_row_and_with_the_scheme(self) -> None:
        self.sync()
        scheme = Scheme.objects.get()
        first, second = list(scheme.documents.all())
        first_path, second_path = doc_path(first), doc_path(second)
        first.delete()
        self.assertFalse(first_path.exists())
        self.assertTrue(second_path.exists())
        admin = User.objects.create_superuser(full_name='Root', password=PASSWORD, email='root@example.com')
        Scheme.remove(scheme.pk, admin)
        self.assertFalse(second_path.exists())


class SchemeDocumentApiTests(SchemeApiBase):
    def with_documents(self, title: str = 'Documented', **extra) -> Scheme:
        scheme = self.scheme(title, **extra)
        SchemeDocument.objects.create(scheme=scheme, file=ContentFile(pdf('second'), name='x'), label='Rules', kind='document', position=1,
                                      source_url=f'{HOST}/sites/default/files/rules.pdf')
        SchemeDocument.objects.create(scheme=scheme, file=ContentFile(pdf('first'), name='x'), label='Brochure', kind='brochure', position=0,
                                      source_url=f'{HOST}/sites/default/files/brochure.pdf')
        return scheme

    def detail(self, scheme: Scheme, **headers):
        return self.as_user(self.member()).get(f'/schemes/get/?scheme_id={scheme.scheme_id}', **headers)

    def test_documents_are_our_own_urls_in_position_order(self) -> None:
        scheme = self.with_documents()
        docs = self.detail(scheme).data['data']['documents']
        self.assertEqual([(d['kind'], d['label']) for d in docs], [('brochure', 'Brochure'), ('document', 'Rules')])
        self.assertTrue(all(d['url'].startswith('http://testserver/media/schemes/') and d['url'].endswith('.pdf') for d in docs))
        self.assertEqual([d['sizeBytes'] for d in docs], [len(pdf('first')), len(pdf('second'))])
        self.assertEqual(set(docs[0]), {'kind', 'label', 'url', 'sizeBytes'})

    def test_public_media_base_url_applies_to_documents(self) -> None:
        scheme = self.with_documents()
        with mock.patch.object(Configurations, 'media_base_url', 'https://cdn.example.com'):
            docs = self.detail(scheme).data['data']['documents']
        self.assertTrue(all(d['url'].startswith('https://cdn.example.com/media/schemes/') for d in docs))

    def test_nothing_that_names_the_source_site_or_internals_is_returned(self) -> None:
        scheme = self.with_documents(links=[
            {'kind': 'brochure', 'label': 'Brochure', 'url': f'{HOST}/sites/default/files/brochure.pdf'},
            {'kind': 'website', 'label': 'Official', 'url': 'https://official.gov.in/'},
        ])
        response = self.detail(scheme)
        text = str(response.data).lower()
        self.assertNotIn('govtschemes', text)
        self.assertNotIn('sha256', text)
        self.assertNotIn('source', text.replace('resource', ''))
        self.assertEqual([l['url'] for l in response.data['data']['links']], ['https://official.gov.in/'])

    def test_blank_label_gets_a_default_and_no_documents_is_an_empty_list(self) -> None:
        scheme = self.scheme('Plain')
        self.assertEqual(self.detail(scheme).data['data']['documents'], [])
        SchemeDocument.objects.create(scheme=scheme, file=ContentFile(pdf('x'), name='x'))
        self.assertEqual(self.detail(scheme).data['data']['documents'][0]['label'], 'Document')

    def test_list_rows_do_not_carry_documents(self) -> None:
        self.with_documents()
        row = self.as_user(self.member()).get('/schemes/get_all/').data['data']['data'][0]
        self.assertNotIn('documents', row)

    def test_unpublished_scheme_documents_are_not_exposed(self) -> None:
        scheme = self.with_documents('Hidden', status='pending_review')
        self.assertEqual(self.detail(scheme).status_code, 404)

    def test_detail_uses_a_fixed_number_of_queries(self) -> None:
        scheme = self.with_documents()
        client = self.as_user(self.member())
        with self.assertNumQueries(4):  # scheme, tags, images, documents
            client.get(f'/schemes/get/?scheme_id={scheme.scheme_id}')


class SchemeDocumentAdminTests(SchemeApiBase):
    LIST = '/admin/schemes/scheme/'

    def setUp(self) -> None:
        super().setUp()
        self.reviewer = self.staff('Scheme Reviewers')
        self.client_ = Client()
        self.client_.force_login(self.reviewer)

    def payload(self, scheme: Scheme | None = None, files: tuple[tuple[str, bytes], ...] = (), **overrides) -> dict:
        data = {
            'title': scheme.title if scheme else 'Hand made', 'department': '', 'description': scheme.description if scheme else 'desc',
            'eligibility': scheme.eligibility if scheme else '', 'benefits': scheme.benefits if scheme else '',
            'application_procedure': scheme.application_procedure if scheme else '', 'required_documents': scheme.required_documents if scheme else '',
            'highlights': '', 'contact_details': '', 'links_text': '', 'overview_text': '', 'additional_text': '[]', 'source_url': '', '_save': 'Save',
            'tags-TOTAL_FORMS': '0', 'tags-INITIAL_FORMS': '0', 'tags-MIN_NUM_FORMS': '0', 'tags-MAX_NUM_FORMS': '1000',
            'images-TOTAL_FORMS': '0', 'images-INITIAL_FORMS': '0', 'images-MIN_NUM_FORMS': '0', 'images-MAX_NUM_FORMS': '10',
            'documents-TOTAL_FORMS': str(len(files)), 'documents-INITIAL_FORMS': '0', 'documents-MIN_NUM_FORMS': '0', 'documents-MAX_NUM_FORMS': '10',
        }
        for index, (name, content) in enumerate(files):
            data[f'documents-{index}-file'] = SimpleUploadedFile(name, content)
            data[f'documents-{index}-label'] = f'Doc {index}'
            data[f'documents-{index}-kind'] = 'brochure' if index == 0 else 'document'
            data[f'documents-{index}-position'] = str(index)
        data.update(overrides)
        return data

    def add(self, **kwargs):
        return self.client_.post(self.LIST + 'add/', self.payload(**kwargs), follow=True)

    def edit(self, scheme: Scheme, **kwargs):
        return self.client_.post(f'{self.LIST}{scheme.pk}/change/', self.payload(scheme, **kwargs), follow=True)

    def test_pdf_upload_is_stored_under_a_name_made_from_its_content(self) -> None:
        self.add(files=(('evil.html', PDF + b'upload'),))
        scheme = Scheme.objects.get(title='Hand made')
        document = scheme.documents.get()
        self.assertTrue(doc_path(document).is_file())
        self.assertRegex(document.file.name, rf'^schemes/{scheme.pk}/docs/[0-9a-f]{{24}}\.pdf$')
        self.assertEqual((document.label, document.kind, document.size_bytes, document.source_url), ('Doc 0', 'brochure', len(PDF + b'upload'), None))

    def test_anything_that_is_not_a_pdf_is_rejected(self) -> None:
        for name, content in (('a.pdf', HTML_BYTES), ('b.pdf', PNG), ('c.pdf', SVG), ('d.pdf', b''), ('e.pdf', b'MZ\x90\x00 program')):
            self.add(files=((name, content),))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())
        self.assertEqual(SchemeDocument.objects.count(), 0)

    def test_oversized_pdf_is_rejected(self) -> None:
        with mock.patch.object(Configurations, 'scheme_document_max_bytes', 50):
            self.add(files=(('big.pdf', PDF + b'x' * 100),))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())

    def test_the_same_pdf_twice_is_attached_once(self) -> None:
        self.add(files=(('a.pdf', PDF + b'same'), ('b.pdf', PDF + b'same')))
        self.assertEqual(Scheme.objects.get(title='Hand made').documents.count(), 1)

    def test_uploading_to_an_imported_scheme_protects_it_from_the_sync(self) -> None:
        scheme = self.scheme('Imported one')
        self.edit(scheme, files=(('mine.pdf', PDF + b'mine'),))
        scheme.refresh_from_db()
        self.assertEqual((scheme.documents.count(), scheme.locally_edited), (1, True))

    def test_removing_a_document_deletes_its_file(self) -> None:
        scheme = self.scheme('Imported one')
        document = SchemeDocument.objects.create(scheme=scheme, file=ContentFile(pdf('x'), name='x'), label='L')
        path = doc_path(document)
        self.edit(scheme, **{'documents-TOTAL_FORMS': '1', 'documents-INITIAL_FORMS': '1', 'documents-0-document_id': document.pk,
                             'documents-0-scheme': scheme.pk, 'documents-0-label': 'L', 'documents-0-kind': 'document',
                             'documents-0-position': '0', 'documents-0-DELETE': 'on'})
        self.assertFalse(SchemeDocument.objects.exists())
        self.assertFalse(path.exists())

    def test_at_most_ten_documents(self) -> None:
        self.add(files=tuple((f'{i}.pdf', PDF + str(i).encode()) for i in range(11)))
        self.assertFalse(Scheme.objects.filter(title='Hand made').exists())

    def test_the_admin_page_offers_a_document_upload(self) -> None:
        scheme = self.scheme('Imported one')
        self.assertContains(self.client_.get(f'{self.LIST}{scheme.pk}/change/'), 'documents-0-file')

    def test_permissions(self) -> None:
        codes = set(Group.objects.get(name='Scheme Reviewers').permissions.values_list('codename', flat=True))
        self.assertTrue({'view_schemedocument', 'add_schemedocument', 'change_schemedocument', 'delete_schemedocument'} <= codes)
        scheme = self.scheme('Imported one')
        other = Client()
        other.force_login(self.staff('Member Managers'))
        other.post(f'{self.LIST}{scheme.pk}/change/', self.payload(scheme, files=(('x.pdf', PDF + b'z'),)))
        self.assertEqual(SchemeDocument.objects.count(), 0)


# ======================================================================== media verification and self-healing

class SyncMediaHealingTests(SyncBase):
    PAGE = staticmethod(lambda title='Old': page(title, images=('/sites/default/files/2024-01/a.jpg',), links=(('Guide', DOC_B),)))

    def legacy(self, slug: str = 'old-scheme', with_hash: bool = False, **extra) -> Scheme:
        """A scheme as an older version imported it: no pictures, no PDFs, media never verified."""
        parsed = parse_scheme_page(self.PAGE(), url(slug))
        return Scheme.objects.create(
            title='Old', source_url=url(slug), description='x', status='published',
            source_lastmod=datetime(2024, 5, 1, tzinfo=dt_timezone.utc),
            content_hash=parsed.content_hash() if with_hash else '', **extra,
        )

    def source(self, *slugs: str, lastmod: str = '2024-05-01', **kwargs) -> FakeSource:
        slugs = slugs or ('old-scheme',)
        return FakeSource(sitemap(*[(url(s), lastmod) for s in slugs]), {url(s): self.PAGE() for s in slugs}, **kwargs)

    def test_scheme_imported_before_media_existed_is_healed_by_a_normal_sync(self) -> None:
        """The reported bug: pictures and PDFs stayed empty because the sync skipped 'unchanged' pages."""
        legacy = self.legacy()
        source = self.source()
        run = self.run_sync(source)  # no force
        legacy.refresh_from_db()
        self.assertEqual(source.fetched, [url('old-scheme')])
        self.assertEqual((legacy.images.count(), legacy.documents.count(), run.status), (1, 1, 'success'))
        self.assertIsNotNone(legacy.media_synced_at)
        self.assertEqual(legacy.expected_media, {'images': [IMG_A], 'documents': [DOC_B]})

    def test_healed_even_when_the_page_content_is_identical(self) -> None:
        legacy = self.legacy(with_hash=True)
        run = self.run_sync(self.source())
        self.assertEqual((run.updated, legacy.images.count(), legacy.documents.count()), (0, 1, 1))

    def test_the_requeue_is_visible_in_the_run_log(self) -> None:
        self.legacy()
        run = self.run_sync(self.source())
        self.assertIn('never fully synced', run.error_summary)

    def test_a_verified_scheme_is_not_fetched_again(self) -> None:
        self.legacy()
        self.run_sync(self.source())
        source = self.source()
        run = self.run_sync(source)
        self.assertEqual((source.fetched, source.fetched_images, source.fetched_documents, run.unchanged), ([], [], [], 1))

    def test_a_page_without_any_media_is_verified_and_not_refetched(self) -> None:
        bare = page('Bare', images=(), links=())
        source = FakeSource(sitemap((url('bare-scheme'), '2024-05-01')), {url('bare-scheme'): bare})
        self.run_sync(source)
        scheme = Scheme.objects.get()
        self.assertIsNotNone(scheme.media_synced_at)
        self.assertEqual(scheme.expected_media, {'images': [], 'documents': []})
        source.fetched.clear()
        self.run_sync(source)
        self.assertEqual(source.fetched, [])

    def test_failed_download_stays_pending_and_is_retried_without_a_page_change(self) -> None:
        self.legacy()
        run = self.run_sync(self.source(images={IMG_A: SourceError('HTTP 500')}))
        scheme = Scheme.objects.get()
        self.assertEqual((run.status, run.media_pending, scheme.media_synced_at), ('partial', 1, None))
        self.assertIn('still waiting', run.error_summary)
        healed = self.run_sync(self.source())
        scheme.refresh_from_db()
        self.assertEqual((healed.media_pending, scheme.images.count(), scheme.media_synced_at is not None), (0, 1, True))

    def test_a_healthy_run_reports_nothing_pending(self) -> None:
        self.assertEqual(self.run_sync(self.source('a-scheme', 'b-scheme')).media_pending, 0)

    def test_admin_owned_and_manual_schemes_are_never_requeued_for_media(self) -> None:
        self.legacy('edited-scheme', locally_edited=True)
        self.legacy('manual-scheme', is_manual=True)
        source = self.source('edited-scheme', 'manual-scheme')
        run = self.run_sync(source)
        self.assertEqual((source.fetched, run.media_pending, SchemeImage.objects.count()), ([], 0, 0))

    def test_robots_blocked_media_does_not_keep_a_scheme_pending_forever(self) -> None:
        self.legacy()
        run = self.run_sync(self.source(blocked=(IMG_A,)))
        scheme = Scheme.objects.get()
        self.assertEqual((run.media_pending, scheme.expected_media['images'], scheme.images.count()), (0, [], 0))

    def test_run_limit_leaves_the_rest_pending_without_errors(self) -> None:
        for slug in ('a-scheme', 'b-scheme', 'c-scheme'):
            self.legacy(slug)
        run = self.run_sync(self.source('a-scheme', 'b-scheme', 'c-scheme'), limit=1)
        self.assertEqual((run.fetched, run.media_pending, run.errors, run.status), (1, 2, 0, 'success'))
        again = self.run_sync(self.source('a-scheme', 'b-scheme', 'c-scheme'))
        self.assertEqual((again.fetched, again.media_pending), (2, 0))


class CheckSchemeMediaCommandTests(SyncBase):
    def build(self, *slugs: str):
        slugs = slugs or ('one-scheme', 'two-scheme')
        html = page('Pic', images=('/sites/default/files/2024-01/a.jpg',), links=(('Guide', DOC_B),))
        source = FakeSource(sitemap(*[(url(s), '2024-05-01') for s in slugs]), {url(s): html for s in slugs})
        self.run_sync(source)
        return source

    def check(self, *args, **kwargs) -> str:
        out = StringIO()
        call_command('check_scheme_media', *args, stdout=out, **kwargs)
        return out.getvalue()

    def failing(self, *args, **kwargs) -> str:
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('check_scheme_media', *args, stdout=out, **kwargs)
        return out.getvalue()

    def fake_network(self, source: FakeSource):
        return mock.patch('gmp_apps.schemes.sync.runner.SchemeSource', return_value=source)

    def test_healthy_data_passes_without_touching_the_network(self) -> None:
        self.build()
        with mock.patch('gmp_apps.schemes.sync.runner.SchemeSource', side_effect=AssertionError('network used')):
            out = self.check()
        self.assertIn('OK: 2 imported schemes verified', out)
        self.assertIn('2 pictures and 2 PDFs', out)

    def test_never_synced_scheme_is_reported(self) -> None:
        Scheme.objects.create(title='Legacy', source_url=url('legacy-scheme'), description='x')
        out = self.failing()
        self.assertIn('PROBLEMS: 1 of 1', out)
        self.assertIn('Legacy', out)
        self.assertIn('never fully synced', out)

    def test_a_promised_picture_or_pdf_that_is_not_stored_is_reported(self) -> None:
        self.build()
        first, second = Scheme.objects.order_by('pk')
        first.images.all().delete()
        second.documents.all().delete()
        out = self.failing()
        self.assertIn('picture not stored: a.jpg', out)
        self.assertIn('PDF not stored: rules.pdf', out)

    def test_files_missing_from_storage_are_reported(self) -> None:
        self.build()
        for image in SchemeImage.objects.all():
            media_path(image).unlink()
        for document in SchemeDocument.objects.all()[:1]:
            doc_path(document).unlink()
        out = self.failing()
        self.assertIn('picture file missing from storage', out)
        self.assertIn('PDF file missing from storage', out)

    def test_admin_owned_schemes_are_not_flagged_for_sync_state_only_for_lost_files(self) -> None:
        self.build()
        Scheme.objects.update(locally_edited=True, media_synced_at=None, expected_media={'images': ['x'], 'documents': ['y']})
        self.assertIn('OK', self.check())
        media_path(SchemeImage.objects.first()).unlink()
        self.assertIn('picture file missing from storage', self.failing())

    def test_repair_heals_legacy_missing_rows_and_missing_files_fetching_only_what_is_needed(self) -> None:
        self.build('one-scheme', 'two-scheme', 'three-scheme', 'four-scheme')
        legacy = Scheme.objects.create(title='Legacy', source_url=url('legacy-scheme'), description='x', source_lastmod=datetime(2024, 5, 1, tzinfo=dt_timezone.utc))
        a, b, c, d = Scheme.objects.exclude(pk=legacy.pk).order_by('pk')
        b.images.all().delete()                      # row lost
        media_path(c.images.get()).unlink()          # file lost
        d.documents.all().delete()                   # PDF lost
        sitemap_entries = [(url(s), '2024-05-01') for s in ('one-scheme', 'two-scheme', 'three-scheme', 'four-scheme', 'legacy-scheme')]
        html = page('Pic', images=('/sites/default/files/2024-01/a.jpg',), links=(('Guide', DOC_B),))
        repair_source = FakeSource(sitemap(*sitemap_entries), {u: html for u, _ in sitemap_entries})
        with self.fake_network(repair_source):
            out = self.check('--repair')
        self.assertIn('After repair:', out)
        self.assertIn('OK:', out)
        fetched = sorted(repair_source.fetched)
        self.assertEqual(fetched, sorted([url('two-scheme'), url('three-scheme'), url('four-scheme'), url('legacy-scheme')]))
        self.assertNotIn(url('one-scheme'), fetched)  # the healthy one is left alone
        self.assertTrue(all(media_path(i).is_file() for i in SchemeImage.objects.all()))

    def test_repair_cannot_fix_files_owned_by_an_admin_and_says_so(self) -> None:
        self.build('one-scheme')
        Scheme.objects.update(locally_edited=True)
        media_path(SchemeImage.objects.get()).unlink()
        with self.fake_network(FakeSource(sitemap(), {})):
            out = self.failing('--repair')
        self.assertIn('owned by an admin', out)
        self.assertTrue(SchemeImage.objects.exists())  # the record is not deleted behind the admin's back

    def test_repair_limit_and_show_limit(self) -> None:
        for slug in ('a-scheme', 'b-scheme', 'c-scheme'):
            Scheme.objects.create(title=slug, source_url=url(slug), description='x', source_lastmod=datetime(2024, 5, 1, tzinfo=dt_timezone.utc))
        html = page('Pic', images=('/sites/default/files/2024-01/a.jpg',), links=())
        entries = [(url(s), '2024-05-01') for s in ('a-scheme', 'b-scheme', 'c-scheme')]
        source = FakeSource(sitemap(*entries), {u: html for u, _ in entries})
        with self.fake_network(source):
            out = self.failing('--repair', '--limit', '1', '--show', '1')
        self.assertEqual(len(source.fetched), 1)
        self.assertIn('and', out.split('After repair:')[1])  # "... and N more (use --show)"
        self.assertEqual(Scheme.objects.filter(media_synced_at__isnull=True).count(), 2)

    def test_repair_refuses_to_run_next_to_another_sync(self) -> None:
        Scheme.objects.create(title='Legacy', source_url=url('legacy-scheme'), description='x')
        SchemeSyncRun.objects.create(status='running')
        with self.fake_network(FakeSource(sitemap(), {})), self.assertRaises(CommandError):
            call_command('check_scheme_media', '--repair', stdout=StringIO())


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class SchemeMediaAdminTests(SchemeApiBase):
    LIST = '/admin/schemes/scheme/'

    def setUp(self) -> None:
        super().setUp()
        self.reviewer = self.staff('Scheme Reviewers')
        self.client_ = Client()
        self.client_.force_login(self.reviewer)

    def titles(self, query: str) -> list[str]:
        return sorted(s.title for s in self.client_.get(f'{self.LIST}?{query}').context['cl'].result_list)

    def seed(self) -> None:
        self.scheme('Waiting one', media_synced_at=None)
        self.scheme('Verified one', media_synced_at=timezone.now())
        self.scheme('Edited one', media_synced_at=None, locally_edited=True)
        self.scheme('Manual one', source_url=None, is_manual=True)

    def test_filter_separates_waiting_verified_and_admin_managed(self) -> None:
        self.seed()
        self.assertEqual(self.titles('media=pending'), ['Waiting one'])
        self.assertEqual(self.titles('media=verified'), ['Verified one'])
        self.assertEqual(self.titles('media=admin'), ['Edited one', 'Manual one'])

    def test_column_says_what_the_state_is(self) -> None:
        self.seed()
        body = self.client_.get(self.LIST).content.decode()
        for text in ('waiting for sync', 'verified', 'admin-managed'):
            self.assertIn(text, body)

    def test_publishing_schemes_that_wait_for_media_warns(self) -> None:
        waiting = self.scheme('Waiting one', status='pending_review', media_synced_at=None)
        ok = self.scheme('Verified one', status='pending_review', media_synced_at=timezone.now())
        response = self.client_.post(self.LIST, {'action': 'publish_selected', '_selected_action': [waiting.pk, ok.pk]}, follow=True)
        self.assertContains(response, '1 are still waiting for their pictures/PDFs')
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, 'published')  # warned, not blocked

    def test_sync_log_shows_pending_count_and_scheme_page_shows_the_timestamp(self) -> None:
        SchemeSyncRun.objects.create(status='partial', media_pending=7)
        self.assertContains(self.client_.get('/admin/schemes/schemesyncrun/'), '>7<')
        scheme = self.scheme('Verified one', media_synced_at=timezone.now())
        self.assertContains(self.client_.get(f'{self.LIST}{scheme.pk}/change/'), 'Media synced at')


class SchemeActiveFlagTests(SchemeApiBase):
    """FG7 item 6: members see Active or Closed; an admin sets it; the sync never touches it."""

    def test_new_schemes_are_active_and_the_flag_is_in_list_and_detail(self) -> None:
        scheme = self.scheme('Open one')
        member = self.as_user(self.member())
        row = member.get('/schemes/get_all/').data['data']['data'][0]
        detail = member.get(f'/schemes/get/?scheme_id={scheme.pk}').data['data']
        self.assertEqual((row['isActive'], detail['isActive']), (True, True))

    def test_a_closed_scheme_is_still_listed_but_shows_closed(self) -> None:
        scheme = self.scheme('Shut one', is_accepting_applications=False)
        member = self.as_user(self.member())
        self.assertEqual(member.get('/schemes/get_all/').data['data']['data'][0]['isActive'], False)
        self.assertEqual(member.get(f'/schemes/get/?scheme_id={scheme.pk}').data['data']['isActive'], False)

    def test_a_hidden_scheme_is_still_hidden_whatever_the_flag(self) -> None:
        scheme = self.scheme('Hidden one', status='unpublished')
        member = self.as_user(self.member())
        self.assertEqual(member.get('/schemes/get_all/').data['data']['data'], [])
        self.assertEqual(member.get(f'/schemes/get/?scheme_id={scheme.pk}').status_code, 404)

    def test_the_flag_appears_in_the_dashboard_schemes_section(self) -> None:
        self.scheme('Shut one', is_accepting_applications=False)
        sections = {s['key']: s for s in self.as_user(self.member()).get('/dashboard/get/').data['data']['sections']}
        self.assertEqual(sections['schemes']['data']['items'][0]['isActive'], False)

    def test_an_admin_can_close_and_reopen_without_marking_the_scheme_as_locally_edited(self) -> None:
        scheme = self.scheme('Imported one')
        client = Client()
        client.force_login(self.staff('Scheme Reviewers'))
        base = SchemeAdminRichTests.form(self, scheme)  # type: ignore[arg-type]
        closed = {k: v for k, v in base.items() if k != 'is_accepting_applications'}   # an unticked checkbox is not sent
        client.post(f'/admin/schemes/scheme/{scheme.pk}/change/', closed, follow=True)
        scheme.refresh_from_db()
        self.assertEqual((scheme.is_accepting_applications, scheme.locally_edited), (False, False))
        client.post(f'/admin/schemes/scheme/{scheme.pk}/change/', base, follow=True)
        scheme.refresh_from_db()
        self.assertTrue(scheme.is_accepting_applications)

    def test_the_admin_list_can_be_filtered_by_the_flag(self) -> None:
        self.scheme('Open one')
        self.scheme('Shut one', is_accepting_applications=False)
        client = Client()
        client.force_login(self.staff('Scheme Reviewers'))
        page_ = client.get('/admin/schemes/scheme/?is_accepting_applications__exact=0')
        self.assertContains(page_, 'Shut one')
        self.assertNotContains(page_, 'Open one')
        self.assertIn('is_accepting_applications', [getattr(spec, 'field_path', None) for spec in page_.context['cl'].filter_specs])


class SchemeActiveFlagSyncTests(SyncBase):
    def test_a_content_update_from_the_source_keeps_the_admins_closed_flag(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        Scheme.objects.update(status='published', is_accepting_applications=False)
        run = self.run_sync(self.source({'alpha-scheme': ('2024-06-01', page('Alpha', benefits=('Now Rs. 9000',)))}))
        self.assertEqual(run.updated, 1)
        self.assertFalse(Scheme.objects.get().is_accepting_applications)

    def test_a_scheme_found_by_the_sync_starts_active(self) -> None:
        self.run_sync(self.source({'alpha-scheme': ('2024-05-01', page('Alpha'))}))
        self.assertTrue(Scheme.objects.get().is_accepting_applications)
