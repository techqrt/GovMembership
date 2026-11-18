import logging
from collections.abc import Callable
from typing import Any

from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response

from gmp.constants import Constants
from gmp_apps.common.exceptions.errors import (
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TokenErrors,
    TooManyRequestsError,
    ValidationErrors,
)
from gmp_apps.common.utils import Utils

logger = logging.getLogger(__name__)


class Common:
    """View-method decorator mapping expected failures to the right status code.

    Unlike PMS, unexpected errors are logged and returned as a generic 500, never
    as a 400 carrying the raw database message.
    """

    def exception_handler(self, func: Callable[..., Response]) -> Callable[..., Response]:
        def exceptions(*args: Any, **kwargs: Any) -> Response:
            try:
                return func(*args, **kwargs)
            except ValueError as error:
                return self._error(status.HTTP_400_BAD_REQUEST, Constants.validation_error, [str(error)])
            except ValidationErrors as error:
                return self._error(status.HTTP_400_BAD_REQUEST, Constants.validation_error, error.errors)
            except TokenErrors as error:
                return self._error(status.HTTP_401_UNAUTHORIZED, Constants.unauthorized, error.errors)
            except ForbiddenError as error:
                return self._error(status.HTTP_403_FORBIDDEN, Constants.forbidden_access, [str(error)])
            except NotFoundError as error:
                return self._error(status.HTTP_404_NOT_FOUND, Constants.not_found, [str(error)])
            except ServiceUnavailableError as error:
                return self._error(status.HTTP_503_SERVICE_UNAVAILABLE, 'Service unavailable', [str(error)])
            except TooManyRequestsError as error:
                return self._error(status.HTTP_429_TOO_MANY_REQUESTS, 'Too many requests', [str(error)])
            except IntegrityError:
                logger.exception('Integrity error')
                return self._error(status.HTTP_409_CONFLICT, 'Conflict', ['The record conflicts with an existing one'])
            except Exception as error:
                logger.exception('Unhandled error')
                return self._error(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    Utils.env_exception_handler(message=str(error)),
                    [Constants.server_error],
                )

        return exceptions

    @staticmethod
    def _error(status_code: int, message: str, errors: list[str]) -> Response:
        return Response(status=status_code, data=Utils.error_response_data(message=message, error=errors))
