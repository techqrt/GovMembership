from collections.abc import Callable
from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.common.utils import Utils


class SerializerValidations:
    """Validates the request, builds a dataclass into request.params, injects user_id."""

    def __init__(self, serializer: type) -> None:
        self.serializer = serializer

    def validate(self, func: Callable[..., Response]) -> Callable[..., Response]:
        def validator(*args: Any, **kwargs: Any) -> Response:
            request: Request = args[0]
            serializer = self.serializer(data=Utils.request_data(request=request))
            if not serializer.is_valid():
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data=Utils.error_response_data(message=Constants.validation_error, error=[serializer.errors]),
                )
            params = serializer.create(serializer.validated_data)
            if request.method == 'GET':
                params.present_url = request.build_absolute_uri()
            params.user_id = getattr(request.user, 'user_id', None)
            params.client_ip = request.META.get('REMOTE_ADDR')
            request.params = params
            return func(*args, **kwargs)

        return validator
