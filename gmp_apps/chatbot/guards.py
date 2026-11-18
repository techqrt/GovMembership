"""Deterministic checks on what comes back from the AI provider. The model is never trusted to stay
inside the approved text: numbers and links in a reply must come from the approved entries."""
import re
import unicodedata

from gmp.constants import Constants

CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
URL = re.compile(r'(?:https?://|www\.)[^\s<>"\')\]]+', re.IGNORECASE)
DANGEROUS_SCHEME = re.compile(r'\b(?:javascript|data|vbscript|file)\s*:', re.IGNORECASE)
LIST_MARKER = re.compile(r'(?m)^\s*\(?\d{1,2}[.)]\s+')
THOUSANDS = re.compile(r'(?<=\d)[,٬](?=\d)')
LANGUAGE = re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$')
MAX_REPLY_CHARS = 3000


def clean_question(text: str, max_chars: int) -> str:
    cleaned = ' '.join(CONTROL.sub(' ', text or '').split())
    if not cleaned:
        raise ValueError(Constants.chatbot_empty_question)
    if len(cleaned) > max_chars:
        raise ValueError(Constants.chatbot_question_too_long)
    return cleaned


def safe_language(value: object) -> str:
    """Language code from the model, reduced to a safe short code ('und' when it is anything else)."""
    code = str(value or '').strip().lower()[:12]
    return code if LANGUAGE.match(code) else 'und'


def base_language(code: str) -> str:
    return code.split('-')[0]


def _ascii_digits(text: str) -> str:
    return ''.join(str(unicodedata.digit(ch, '')) if ch.isdigit() else ch for ch in text)


def numbers_in(text: str) -> set[str]:
    """Every number in the text, whatever script its digits are written in, ignoring list numbering
    and thousands separators (so 5,000 and 5000 and ५,००० are the same number)."""
    plain = THOUSANDS.sub('', LIST_MARKER.sub('', _ascii_digits(text)))
    return set(re.findall(r'\d+', plain))


def urls_in(text: str) -> set[str]:
    return {match.rstrip('.,;:!?').lower().rstrip('/') for match in URL.findall(text)}


def ungrounded_reason(reply: str, approved_texts: list[str], allowed_urls: list[str]) -> str | None:
    """Why a reply must not be shown, or None if it stays inside the approved material."""
    if not reply.strip():
        return 'empty reply'
    if len(reply) > MAX_REPLY_CHARS:
        return 'reply too long'
    if DANGEROUS_SCHEME.search(reply):
        return 'dangerous link scheme'
    approved_numbers: set[str] = set()
    approved_urls = {u.lower().rstrip('/') for u in allowed_urls}
    for text in approved_texts:
        approved_numbers |= numbers_in(text)
        approved_urls |= urls_in(text)
    if numbers_in(reply) - approved_numbers:
        return 'number not in the approved answer'
    if urls_in(reply) - approved_urls:
        return 'link not in the approved material'
    return None
