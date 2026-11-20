from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle


class DocumentUploadThrottle(SimpleRateThrottle):
    """Per-member limit on uploads per hour, on top of the per-member file caps."""

    scope = 'member_document_upload'

    def get_cache_key(self, request: Request, view: object) -> str:
        return self.cache_format % {'scope': self.scope, 'ident': f'u{request.user.pk}'}
