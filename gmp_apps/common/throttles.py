from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    """Per-IP throttle for unauthenticated auth endpoints (login, OTP, reset)."""

    scope = 'auth'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class ContactSubmitThrottle(SimpleRateThrottle):
    """Per-IP limit for the public Contact Us form (no login, so this is the main brake on floods)."""

    scope = 'contact_submit'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class ContactCategoryThrottle(SimpleRateThrottle):
    """Per-IP limit for the public list of Contact Us topics (its own bucket, so it cannot use up a login budget)."""

    scope = 'contact_category'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
