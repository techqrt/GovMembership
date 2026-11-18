import math
from typing import Any
from urllib.parse import urlsplit

from django.db.models import QuerySet
from rest_framework.request import Request

from gmp.config import Configurations
from gmp.constants import Constants


class Utils:
    @staticmethod
    def success_response_data(message: str | None, data: list | dict | None = None) -> dict[str, Any]:
        response: dict[str, Any] = {'status': True}
        if message is not None:
            response['message'] = message
        if data is not None:
            response['data'] = data
        return response

    @staticmethod
    def error_response_data(message: str, error: list[Any]) -> dict[str, Any]:
        return {'status': False, 'message': message, 'error': error}

    @staticmethod
    def env_exception_handler(message: str) -> str:
        """Raw internals only in DEBUG; generic message otherwise."""
        return message if Configurations.debug else Constants.server_error

    @staticmethod
    def public_base_url(request_url: str) -> str:
        """Public base of our own server for absolute media URLs (MEDIA_BASE_URL wins if set)."""
        if Configurations.media_base_url:
            return Configurations.media_base_url.rstrip('/')
        parts = urlsplit(request_url)
        return f'{parts.scheme}://{parts.netloc}'

    @staticmethod
    def paginate_queryset(queryset: QuerySet, page_num: int, limit: int) -> tuple[list, int]:
        """Slice at the database level. Returns (rows, total_pages)."""
        total_rows = queryset.count()
        total_page = max(math.ceil(total_rows / limit), 1)
        if page_num > total_page:
            raise ValueError(Constants.page_num_exceeded)
        start = (page_num - 1) * limit
        return list(queryset[start:start + limit]), total_page

    @staticmethod
    def add_page_parameter(
        final_data: list,
        page_num: int,
        total_page: int,
        present_url: str,
    ) -> dict[str, Any]:
        to_return: dict[str, Any] = {'data': final_data, 'presentPage': page_num, 'totalPage': total_page}
        if page_num < total_page:
            to_return['nextPageUrl'] = Utils._page_url(present_url, page_num + 1)
        if page_num > 1:
            to_return['previousPageUrl'] = Utils._page_url(present_url, page_num - 1)
        return to_return

    @staticmethod
    def _page_url(url: str, page_num: int) -> str:
        base, _, query = url.partition('?')
        pairs = [p for p in query.split('&') if p and not p.startswith('page_num=')]
        pairs.append(f'page_num={page_num}')
        return f'{base}?{"&".join(pairs)}'

    @staticmethod
    def request_data(request: Request) -> dict[str, Any]:
        """Query params overlaid with body fields (body wins)."""
        data: dict[str, Any] = dict(request.query_params.items())
        body = request.data
        if hasattr(body, 'items'):
            data.update(dict(body.items()))
        return data
