from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class ChatbotRateThrottle(SimpleRateThrottle):
    """Per-member limit on questions per minute (the daily cap is enforced from the log)."""

    scope = 'chatbot'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': f'u{request.user.pk}'}
