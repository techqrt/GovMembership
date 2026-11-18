import dataclasses
import hashlib
import json
import re
from urllib.parse import urlsplit

from gmp_apps.schemes.sync.dom import Node, collapse, is_noise, parse_html, plain_text, render_lines

MAX_FIELD_CHARS = 20_000
MAX_CONTACT_CHARS = 5_000
MAX_TITLE_CHARS = 300
MAX_IMAGES = 5
MAX_LINKS = 30
MAX_TAGS = 20
MAX_OVERVIEW_ROWS = 30
MAX_ADDITIONAL_SECTIONS = 40
HEADING_MARK = '\x00H:'
SOURCE_FILES_PREFIX = '/sites/default/files/'

# Heading text (lower-cased, punctuation stripped) -> field. A heading goes to the first matching field.
SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ('description', re.compile(r'^(scheme )?(introduction|overview|about)\b')),
    ('benefits', re.compile(
        r'^(scheme )?benefits?\b|^benefits? (of|under)\b|^key benefits?\b|^(key )?features( of (the )?scheme)?$|'
        r'^amount of (scholarship|assistance|subsidy|benefit|grant|pension)\b',
    )),
    ('eligibility', re.compile(
        r'^(eligibility|who (can|is) (apply|eligible)|who is not eligible|not eligible|ineligib|'
        r'eligible (beneficiar|candidate|applicant|person|citizen))',
    )),
    ('required_documents', re.compile(r'^((required|important|necessary) )?documents?\b')),
    ('application_procedure', re.compile(
        r'^(how to apply|steps to apply|application (process|procedure)|apply(ing)? (online|offline|process)|'
        r'procedure to apply|process to apply|how can i apply|(online|offline)( (application|apply|registration))?'
        r'( (process|procedure|mode))?$|renewal process|registration process)',
    )),
]
LINK_HEADING = re.compile(r'^((important|relevant|useful|official|quick) )?links?\b')
CONTACT_HEADING = re.compile(r'^(contact (details|information|us)|helpline)')
DROP_HEADING = re.compile(r'^(matching schemes|comments?)\b')
TABLE_FALLBACKS: list[tuple[str, re.Pattern[str]]] = [
    ('eligibility', re.compile(r'^(who can (be )?eligible|eligibility|beneficiaries)\b')),
    ('application_procedure', re.compile(r'^(mode of appl|how to apply|application (mode|process))')),
]
DEPARTMENT_LABEL = re.compile(r'^(nodal\s+)?(department|ministry|agency|authority)\b|^implementing (agency|department)\b')
EMPTY_VALUE = re.compile(r'^(not known|not available|not specified|n/?a|none|-+)\b', re.IGNORECASE)
NOISE_ROW_LABELS = {'subscription', 'subscribe'}
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
TAG_FIELDS = (('scheme_type', 'field-scheme-type'), ('person_type', 'field-person-type'), ('caste', 'field-caste'))


@dataclasses.dataclass
class ParsedScheme:
    title: str
    description: str = ''
    eligibility: str = ''
    benefits: str = ''
    application_procedure: str = ''
    required_documents: str = ''
    department: str = ''
    highlights: str = ''
    contact_details: str = ''
    images: list[str] = dataclasses.field(default_factory=list)
    links: list[dict[str, str]] = dataclasses.field(default_factory=list)
    overview: list[dict[str, str]] = dataclasses.field(default_factory=list)
    tags: list[dict[str, str]] = dataclasses.field(default_factory=list)
    additional_sections: list[dict[str, str]] = dataclasses.field(default_factory=list)

    def has_content(self) -> bool:
        return any((
            self.description, self.eligibility, self.benefits, self.application_procedure, self.required_documents,
            self.highlights, self.additional_sections,
        ))

    def content_hash(self) -> str:
        """Stable fingerprint of everything we store, to detect source changes."""
        payload = json.dumps(dataclasses.asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()


def parse_scheme_page(html: str, page_url: str) -> ParsedScheme | None:
    """Extract a scheme from one source page, or None if it is not a scheme page.

    Everything meaningful on the page is kept: the five core sections, every other section (as
    `additional_sections`), highlights, links, contact details, the overview table and tags. Only
    plain text and validated http(s) URLs are produced, so nothing from the remote page can inject
    markup or script downstream. User comments, ads, scripts and forum blocks are never read.
    """
    root = parse_html(html)
    article = _find_article(root)
    if article is None:
        return None
    title = _title(root)
    body = _main_body(article)
    if not title or body is None:
        return None
    sections = _split_sections(render_lines(body, mark_headings=True))
    fields, contact_lines, additional, preamble_text, links_without_anchors = _classify(sections)
    link_urls = _links(article, body, page_url)
    highlights = _highlights(article)
    rows = _table_rows(sections)
    overview = _overview(sections)
    tags, ministries = _tags(article)

    description = fields.get('description') or preamble_text or highlights
    if fields.get('description') and preamble_text:
        additional.insert(0, {'heading': 'Overview', 'text': _clip(preamble_text)})
    if not link_urls:
        additional.extend(links_without_anchors)  # a "links" section with only text, e.g. "form will be released soon"
    scheme = ParsedScheme(
        title=title,
        description=description,
        eligibility=fields.get('eligibility') or rows.get('eligibility', ''),
        benefits=fields.get('benefits') or highlights,
        application_procedure=fields.get('application_procedure') or rows.get('application_procedure', ''),
        required_documents=fields.get('required_documents', ''),
        department=_department(sections) or (ministries[0] if ministries else ''),
        highlights=highlights,
        contact_details=_contact(contact_lines, article),
        images=_images(article, page_url),
        links=link_urls,
        overview=overview,
        tags=tags,
        additional_sections=additional[:MAX_ADDITIONAL_SECTIONS],
    )
    return scheme if scheme.has_content() else None


# ---------- page structure ----------

def _find_article(root: Node) -> Node | None:
    for node in root.iter_nodes():
        if node.tag == 'article' and 'data-history-node-id' in node.attrs:
            return node
    return None


def _title(root: Node) -> str:
    for node in root.iter_nodes():
        if node.tag == 'h1':
            text = plain_text(node)
            if text:
                return text[:MAX_TITLE_CHARS]
    for node in root.iter_nodes():
        if node.tag == 'title':
            return collapse(plain_text(node).split('|')[0])[:MAX_TITLE_CHARS]
    return ''


def _main_body(article: Node) -> Node | None:
    """The article's own text body: the largest `body` field (site widgets and ads are small)."""
    best: Node | None = None
    best_size = 80
    for node in article.iter_nodes():
        if node.tag == 'div' and node.has_class('field--name-body') and not _in_noise(node, article):
            size = len(plain_text(node))
            if size > best_size:
                best, best_size = node, size
    return best


def _in_noise(node: Node, stop: Node) -> bool:
    current: Node | None = node
    while current is not None and current is not stop:
        if is_noise(current):
            return True
        current = current.parent
    return False


def _split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [('', [])]
    for line in lines:
        if line.startswith(HEADING_MARK):
            sections.append((line[len(HEADING_MARK):], []))
        else:
            sections[-1][1].append(line)
    return sections


def _normalize_heading(heading: str) -> str:
    return collapse(re.sub(r'[^a-z0-9 ]+', ' ', heading.lower()))


def _clip(text: str, limit: int = MAX_FIELD_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rsplit('\n', 1)[0]


# ---------- sections ----------

def _classify(sections: list[tuple[str, list[str]]]):
    """Route every section somewhere: a core field, contact, links, or `additional_sections`."""
    collected: dict[str, list[tuple[str, list[str]]]] = {}
    contact_lines: list[str] = []
    additional: list[dict[str, str]] = []
    links_without_anchors: list[dict[str, str]] = []
    preamble_lines: list[str] = []
    for heading, lines in sections:
        if not heading:
            preamble_lines = [line for line in lines if ' | ' not in line]  # table rows go to `overview`
            continue
        if not lines:
            continue  # e.g. a "Frequently Asked Questions" banner; its questions are sections of their own
        normalized = _normalize_heading(heading)
        if DROP_HEADING.search(normalized):
            continue
        if CONTACT_HEADING.search(normalized):
            contact_lines.extend(lines)
        elif LINK_HEADING.search(normalized):
            links_without_anchors.append({'heading': heading[:200], 'text': _clip('\n'.join(lines))})
        else:
            field = next((name for name, pattern in SECTION_PATTERNS if pattern.search(normalized)), None)
            if field:
                collected.setdefault(field, []).append((heading, lines))
            else:
                additional.append({'heading': heading[:200], 'text': _clip('\n'.join(lines))})
    fields = {name: _join_sections(parts) for name, parts in collected.items()}
    return fields, contact_lines, additional, _clip('\n'.join(preamble_lines)), links_without_anchors


def _join_sections(parts: list[tuple[str, list[str]]]) -> str:
    """One section reads as-is; several sections for one field keep their sub-headings."""
    if len(parts) == 1:
        return _clip('\n'.join(parts[0][1]))
    return _clip('\n\n'.join('\n'.join([heading.strip(' :-'), *lines]) for heading, lines in parts))


def _highlights(article: Node) -> str:
    for node in article.iter_nodes():
        if node.tag == 'div' and node.has_class('field--name-field-highlights') and not _in_noise(node, article):
            lines = [line for line in render_lines(node) if line.lower() != 'highlights']
            return _clip('\n'.join(lines))
    return ''


def _contact(contact_lines: list[str], article: Node) -> str:
    """Contact section text (helpline, email), falling back to the page's 'Customer Care' block."""
    lines = contact_lines
    if not lines:
        for node in article.iter_nodes():
            if node.attrs.get('id') == 'icc' and not _in_noise(node, article):
                lines = [line for line in render_lines(node) if line.lower() != 'customer care']
                break
    return _clip('\n'.join(lines), MAX_CONTACT_CHARS)


# ---------- overview table, department ----------

def _table_rows(sections: list[tuple[str, list[str]]]) -> dict[str, str]:
    """Overview-table rows ("Who can eligible | ...") used only when a section heading is missing."""
    found: dict[str, str] = {}
    for _, lines in sections:
        for line in lines:
            cells = [cell.strip() for cell in line.split(' | ')]
            if len(cells) < 2:
                continue
            label = _normalize_heading(cells[0])
            value = collapse(' '.join(cells[1:])).strip(' :')
            if not value or EMPTY_VALUE.match(value):
                continue
            for field, pattern in TABLE_FALLBACKS:
                if pattern.search(label) and field not in found:
                    found[field] = value[:MAX_FIELD_CHARS]
    return found


def _overview(sections: list[tuple[str, list[str]]]) -> list[dict[str, str]]:
    """The 'overview of the scheme' table before the first heading, as label/value pairs."""
    rows: list[dict[str, str]] = []
    for line in sections[0][1]:
        cells = [cell.strip() for cell in line.split(' | ')]
        if len(cells) < 2:
            continue
        label = collapse(cells[0]).strip(' :')
        value = collapse(' '.join(cells[1:])).strip(' :')
        if not label or not value or EMPTY_VALUE.match(value) or label.lower() in NOISE_ROW_LABELS:
            continue
        rows.append({'label': label[:100], 'value': value[:500]})
        if len(rows) >= MAX_OVERVIEW_ROWS:
            break
    return rows


def _department(sections: list[tuple[str, list[str]]]) -> str:
    """Department from an overview table row such as 'Ministry | Ministry Of Minority Affairs'."""
    for _, lines in sections:
        for line in lines:
            cells = [cell.strip() for cell in line.split(' | ')]
            if len(cells) < 2:
                continue
            label = _normalize_heading(cells[0])
            value = collapse(' '.join(cells[1:])).strip(' :.-')
            if DEPARTMENT_LABEL.search(label) and value and not EMPTY_VALUE.match(value):
                return value[:200]
    return ''


# ---------- links ----------

def _clean_link(href: str, label: str, page_url: str) -> dict[str, str] | None:
    """A link we are willing to store: absolute http(s), or a file hosted on the source itself.
    javascript:, data:, mailto:, tel:, obfuscated-email and site-navigation links are refused."""
    href = (href or '').strip()
    source = urlsplit(page_url)
    if href.startswith(SOURCE_FILES_PREFIX):
        href = f'{source.scheme}://{source.netloc}{href}'
    parts = urlsplit(href)
    if parts.scheme not in ('http', 'https') or not parts.netloc or len(href) > 500 or re.search(r'[\s\x00-\x1f]', href):
        return None
    if parts.netloc.lower() == source.netloc.lower() and not parts.path.startswith(SOURCE_FILES_PREFIX):
        return None  # the source's own navigation, not something about this scheme
    return {'label': collapse(label)[:200] or parts.netloc, 'url': href}


def _links(article: Node, body: Node, page_url: str) -> list[dict[str, str]]:
    """Official website, information brochure, then the anchors under the page's links headings."""
    found: list[dict[str, str]] = []

    def add(kind: str, anchor: Node) -> None:
        link = _clean_link(anchor.attrs.get('href', ''), plain_text(anchor) or anchor.attrs.get('title', ''), page_url)
        if link and all(existing['url'] != link['url'] for existing in found) and len(found) < MAX_LINKS:
            found.append({'kind': kind, **link})

    for kind, field in (('website', 'field--name-field-website'), ('brochure', 'field--name-field-information-brochure')):
        for node in article.iter_nodes():
            if node.tag == 'div' and node.has_class(field) and not _in_noise(node, article):
                for anchor in node.iter_nodes():
                    if anchor.tag == 'a':
                        add(kind, anchor)
                break
    in_links_section = False
    for node in body.iter_nodes():
        if node.tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            in_links_section = bool(LINK_HEADING.search(_normalize_heading(plain_text(node))))
        elif in_links_section and node.tag == 'a' and not _in_noise(node, article):
            add('link', node)
    return found


# ---------- tags, images ----------

def _tags(article: Node) -> tuple[list[dict[str, str]], list[str]]:
    """Taxonomy terms (scheme type, person type, caste) and any ministry term."""
    tags: list[dict[str, str]] = []
    ministries: list[str] = []

    def names(container: Node) -> list[str]:
        return [plain_text(n)[:100] for n in container.iter_nodes() if n.has_class('field--name-name') and plain_text(n)]

    for node in article.iter_nodes():
        if node.tag != 'div' or _in_noise(node, article):
            continue
        for group, field in TAG_FIELDS:
            if node.has_class(f'field--name-{field}'):
                for name in names(node):
                    tag = {'group': group, 'name': name}
                    if tag not in tags and len(tags) < MAX_TAGS:
                        tags.append(tag)
        if node.has_class('field--name-field-ministry'):
            ministries.extend(name for name in names(node) if name not in ministries)
    return tags, ministries


def _images(article: Node, page_url: str) -> list[str]:
    """Scheme pictures only: original uploads, not resized styles, author avatars, term icons or leader photos."""
    host = urlsplit(page_url)
    images: list[str] = []
    for node in article.iter_nodes():
        if node.tag != 'img' or _in_noise(node, article):
            continue
        path = urlsplit(node.attrs.get('src', '')).path
        if (
            path.startswith(SOURCE_FILES_PREFIX)
            and path.lower().endswith(IMAGE_EXTENSIONS)
            and not any(part in path for part in ('/styles/', '/pictures/', 'term-icon'))
        ):
            url = f'{host.scheme}://{host.netloc}{path}'
            if url not in images:
                images.append(url)
        if len(images) >= MAX_IMAGES:
            break
    return images
