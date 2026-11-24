"""Which level a scheme belongs to (national or one state), worked out from its department, title and page address.

Rule based and deliberately cautious: when the text does not make it clear, nothing is guessed and the scheme is
left unclassified for an admin to set. The sync only uses this while a scheme has no level; an admin's choice is
never overwritten.
"""
import dataclasses
import re

NATIONAL = 'national'
STATE = 'state'

# The 28 states and 8 union territories (the member app lists the territories as states).
STATES = (
    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh', 'Goa', 'Gujarat', 'Haryana',
    'Himachal Pradesh', 'Jharkhand', 'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
    'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
    'Andaman and Nicobar Islands', 'Chandigarh', 'Dadra and Nagar Haveli and Daman and Diu', 'Delhi',
    'Jammu and Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry',
)
STATE_CHOICES = [(name, name) for name in STATES]

# Other spellings that appear on the source site.
ALIASES = {
    'orissa': 'Odisha', 'uttaranchal': 'Uttarakhand', 'pondicherry': 'Puducherry', 'nct of delhi': 'Delhi',
    'new delhi': 'Delhi', 'andaman & nicobar islands': 'Andaman and Nicobar Islands', 'jammu & kashmir': 'Jammu and Kashmir',
    'j&k': 'Jammu and Kashmir', 'daman and diu': 'Dadra and Nagar Haveli and Daman and Diu',
    'dadra and nagar haveli': 'Dadra and Nagar Haveli and Daman and Diu',
}
_NAMES = {name.lower(): name for name in STATES} | ALIASES
# Longest names first, so "Arunachal Pradesh" is never read as a shorter name inside it.
_STATE_PATTERN = re.compile(
    r'(?<![a-z])(' + '|'.join(re.escape(n) for n in sorted(_NAMES, key=len, reverse=True)) + r')(?![a-z])', re.IGNORECASE,
)
# A department that belongs to the Union government.
_NATIONAL_DEPARTMENT = re.compile(
    r'^\s*ministry\b|\bgovernment of india\b|\bgovt\.? of india\b|\bunion (government|ministry)\b|\bcentral government\b',
    re.IGNORECASE,
)
_NATIONAL_TITLE = re.compile(r'^\s*(pradhan\s+mantri|pm[\s-])', re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class Classification:
    level: str = ''
    state: str = ''
    reason: str = ''


def canonical_state(value: str) -> str | None:
    """The official name for whatever a member or the source calls a state (any capitals, stray or repeated spaces, or a
    known alternative such as Orissa or J&K), or None when it is not a state."""
    return _NAMES.get(' '.join((value or '').split()).lower())


def _states_in(text: str) -> set[str]:
    return {_NAMES[match.group(1).lower()] for match in _STATE_PATTERN.finditer(text or '')}


def _slug(source_url: str | None) -> str:
    """The last part of the page address as words: 'https://x.in/haryana-unmarried-pension-scheme' becomes
    'haryana unmarried pension scheme'."""
    return re.sub(r'[-_]+', ' ', (source_url or '').rstrip('/').rsplit('/', 1)[-1])


def classify(department: str = '', title: str = '', source_url: str | None = None) -> Classification:
    """The first clear answer wins, in this order: a state in the department, a Union department, a state in the
    title, a state in the page address, a Pradhan Mantri title. Two different states in one place is unclear."""
    in_department = _states_in(department)
    if len(in_department) == 1:
        return Classification(STATE, next(iter(in_department)), 'department names the state')
    if len(in_department) > 1:
        return Classification(reason='department names more than one state')
    if _NATIONAL_DEPARTMENT.search(department or ''):
        return Classification(NATIONAL, '', 'department is a Union ministry or government of India body')
    for label, text in (('title', title), ('page address', _slug(source_url))):
        found = _states_in(text)
        if len(found) == 1:
            return Classification(STATE, next(iter(found)), f'{label} names the state')
        if len(found) > 1:
            return Classification(reason=f'{label} names more than one state')
    if _NATIONAL_TITLE.search(title or ''):
        return Classification(NATIONAL, '', 'title is a Pradhan Mantri scheme')
    return Classification(reason='nothing in the department, title or page address makes it clear')
