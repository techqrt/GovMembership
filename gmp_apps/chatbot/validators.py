from urllib.parse import urlsplit

from django.core.exceptions import ValidationError

from gmp_apps.common.url_safety import validate_public_url

# App screens a knowledge entry may point to. The mobile app and website map each key to their own screen.
SCREENS = ('dashboard', 'profile', 'referrals', 'permanent_application', 'schemes', 'portals', 'content', 'support', 'notifications')
MAX_LINKS = 5
MAX_SCREENS = 5


def validate_links(links: object) -> None:
    """Curated links: a list of {label, url}; https public URLs only, at most MAX_LINKS."""
    if not isinstance(links, list) or len(links) > MAX_LINKS:
        raise ValidationError(f'Links must be a list of at most {MAX_LINKS} items')
    for link in links:
        if not isinstance(link, dict) or not isinstance(link.get('label'), str) or not isinstance(link.get('url'), str) or not link['label'].strip():
            raise ValidationError('Every link needs a label and a url')
        validate_public_url(link['url'])
        if urlsplit(link['url']).scheme != 'https':
            raise ValidationError('Curated links must use https')
        if len(link['label']) > 100:
            raise ValidationError('Link labels are limited to 100 characters')


def validate_screens(screens: object) -> None:
    if not isinstance(screens, list) or len(screens) > MAX_SCREENS or any(s not in SCREENS for s in screens) or len(set(screens)) != len(screens):
        raise ValidationError(f'Screens must be up to {MAX_SCREENS} distinct values from: {", ".join(SCREENS)}')
