from typing import Any

from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from gmp.constants import Constants
from gmp_apps.common.utils import Utils


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """DRF-level exceptions (auth, permission, throttle) in the standard error envelope."""
    response = exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        message = Constants.unauthorized
    elif isinstance(exc, PermissionDenied):
        message = Constants.forbidden_access
    elif isinstance(exc, Throttled):
        message = 'Too many requests'
    elif isinstance(exc, ValidationError):
        message = Constants.validation_error
    else:
        message = str(getattr(exc, 'default_detail', 'Error'))
    detail = response.data.get('detail') if isinstance(response.data, dict) else None
    errors = [str(detail)] if detail is not None else [response.data]
    response.data = Utils.error_response_data(message=message, error=errors)
    if response.status_code < status.HTTP_400_BAD_REQUEST:
        response.status_code = status.HTTP_400_BAD_REQUEST
    return response
