import hashlib
from typing import Any

from rest_framework import serializers

from gmp_apps.common.serializers.response.api_response import ApiErrorSerializer

_ENVELOPES: dict[tuple[str, str], type[serializers.Serializer]] = {}


class SwaggerPage:
    @staticmethod
    def envelope(description: str | None, response: type[serializers.Serializer] | None) -> type[serializers.Serializer]:
        """Success envelope class, built once per (data serializer, description) so component names stay unique."""
        key = (response.__name__ if response else '', description or '')
        if key not in _ENVELOPES:
            suffix = hashlib.md5(key[1].encode()).hexdigest()[:6]
            name = f'{key[0] or "Message"}Envelope{suffix}'
            fields: dict[str, Any] = {
                'status': serializers.BooleanField(default=True),
                'message': serializers.CharField(default=key[1]),
            }
            if response:
                fields['data'] = response()
            _ENVELOPES[key] = type(name, (serializers.Serializer,), fields)
        return _ENVELOPES[key]

    @staticmethod
    def response(
        description: str | None = None,
        response: type[serializers.Serializer] | None = None,
        authenticated: bool = True,
    ) -> dict[int, Any]:
        """Documented responses: success envelope plus the error envelope codes."""
        documented: dict[int, Any] = {
            200: SwaggerPage.envelope(description, response),
            400: ApiErrorSerializer,
            429: ApiErrorSerializer,
        }
        if authenticated:
            documented[401] = ApiErrorSerializer
            documented[403] = ApiErrorSerializer
        return documented

    @staticmethod
    def get_all_parameters() -> list[Any]:
        from drf_spectacular.utils import OpenApiParameter

        return [
            OpenApiParameter('values', str, description='Comma separated camelCase keys to return'),
            OpenApiParameter('page_num', int, description='Page number, default 1'),
            OpenApiParameter('limit', int, description='Page size, default 10, max 100'),
            OpenApiParameter('sort_by', str, description='camelCase key to sort by'),
            OpenApiParameter('sort_order', str, enum=['asc', 'desc']),
            OpenApiParameter('filter_key', str, description='camelCase key to filter on (send with filter_value)'),
            OpenApiParameter('filter_value', str),
            OpenApiParameter('search_key', str, description='Free-text search'),
            OpenApiParameter('from_date', str, description='DD-MM-YY'),
            OpenApiParameter('to_date', str, description='DD-MM-YY'),
        ]
