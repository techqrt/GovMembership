from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    """Per-IP throttle for unauthenticated auth endpoints (login, OTP, reset)."""

    scope = 'auth'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
