"""Portal links use the shared public-URL rules (see gmp_apps/common/url_safety.py)."""
from gmp_apps.common.url_safety import url_key, validate_public_url as validate_portal_url

__all__ = ['url_key', 'validate_portal_url']
