"""A small, dependency-free HTML tree for the scheme parser.

Remote HTML is untrusted: depth and size are capped, and nothing from it is ever executed or
stored as markup. Only plain text is extracted.
"""
import re
from html.parser import HTMLParser

MAX_HTML_BYTES = 3_000_000
MAX_DEPTH = 120

VOID_TAGS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr',
}
BLOCK_TAGS = {
    'p', 'div', 'section', 'article', 'ul', 'ol', 'li', 'table', 'tr', 'blockquote', 'pre', 'header', 'footer',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'dl', 'dt', 'dd', 'br', 'hr',
}
HEADING_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
SKIP_TAGS = {'script', 'style', 'noscript', 'iframe', 'form', 'button', 'svg', 'template', 'object', 'embed'}
# Class fragments of site furniture that never belongs to a scheme description.
NOISE_CLASS_FRAGMENTS = ('comment', 'addtoany', 'fav-button', 'table-of-content', 'toc-js', 'scheme-forum', 'forum-invitation')


EMAIL_SHAPE = re.compile(r'^[^@\s<>"]{1,64}@[^@\s<>"]{1,200}\.[^@\s<>"]{2,24}$')


def decode_cf_email(encoded: str) -> str:
    """Cloudflare hides addresses as hex: the first byte is an XOR key for the rest. Anything that
    is not valid hex, or does not decode to an address-shaped string, becomes ''."""
    try:
        raw = bytes.fromhex(encoded.strip())
    except ValueError:
        return ''
    if len(raw) < 4:
        return ''
    key = raw[0]
    try:
        email = bytes(byte ^ key for byte in raw[1:]).decode('utf-8')
    except UnicodeDecodeError:
        return ''
    return email if EMAIL_SHAPE.match(email) else ''


class Node:
    __slots__ = ('tag', 'attrs', 'children', 'parent')

    def __init__(self, tag: str, attrs: dict[str, str], parent: 'Node | None') -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node | str] = []
        self.parent = parent

    @property
    def classes(self) -> str:
        return self.attrs.get('class', '')

    def has_class(self, name: str) -> bool:
        return name in self.classes.split()

    def iter_nodes(self):
        """Depth-first element iterator (iterative, so hostile nesting cannot blow the stack)."""
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed([c for c in node.children if isinstance(c, Node)]))


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node('[document]', {}, None)
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: (v or '') for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS and len(self.stack) < MAX_DEPTH:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Node(tag, {k: (v or '') for k, v in attrs}, self.stack[-1]))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(html[:MAX_HTML_BYTES])
    builder.close()
    return builder.root


def is_noise(node: Node) -> bool:
    if node.tag in SKIP_TAGS:
        return True
    classes = node.classes
    return any(fragment in classes for fragment in NOISE_CLASS_FRAGMENTS)


def collapse(text: str) -> str:
    return ' '.join(text.split())


def plain_text(node: Node) -> str:
    """Inline text of a node, whitespace collapsed, noise skipped."""
    parts: list[str] = []
    stack: list[Node | str] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            parts.append(item)
            continue
        if is_noise(item) and item is not node:
            continue
        if 'data-cfemail' in item.attrs:
            parts.append(decode_cf_email(item.attrs['data-cfemail']))
            continue
        stack.extend(reversed(item.children))
    return collapse(''.join(parts))


def render_lines(node: Node, mark_headings: bool = False) -> list[str]:
    """Readable plain-text lines: paragraphs, "- " list items, table rows as "a | b", optional
    heading markers ("\\x00H:<text>") for section splitting. Noise subtrees are dropped."""
    lines: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = collapse(''.join(current))
        current.clear()
        if text:
            lines.append(text)

    def walk(item: Node, list_item: bool = False) -> None:
        if is_noise(item):
            return
        if 'data-cfemail' in item.attrs:
            current.append(decode_cf_email(item.attrs['data-cfemail']))
            return
        tag = item.tag
        if tag in HEADING_TAGS and mark_headings:
            flush()
            heading = plain_text(item)
            if heading:
                lines.append('\x00H:' + heading)
            return
        if tag == 'tr':
            flush()
            cells = [plain_text(c) for c in item.children if isinstance(c, Node) and c.tag in ('td', 'th')]
            row = ' | '.join(cell for cell in cells if cell)
            if row:
                lines.append(row)
            return
        is_block = tag in BLOCK_TAGS
        if is_block:
            flush()
        if tag == 'li':
            current.append('- ')
        for child in item.children:
            if isinstance(child, str):
                current.append(child)
            else:
                walk(child)
        if is_block:
            flush()

    walk(node)
    flush()
    return lines
