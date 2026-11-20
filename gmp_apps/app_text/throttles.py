from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class AppTextThrottle(SimpleRateThrottle):
    """Per-IP limit for the public app text endpoint (the login and register screens need it before a member signs in)."""

    scope = 'app_text'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
