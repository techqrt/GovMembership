from rest_framework.response import Response

from gmp_apps.authentication.dataclasses.request.get.get_profile import GetProfileRequest
from gmp_apps.authentication.dataclasses.request.update.update_profile import UpdateProfileRequest
from gmp_apps.authentication.models import User
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils


class AuthenticationProfileView:
    """Profile of the caller only: the user is taken from the token, never from a request parameter."""

    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'
        self.data_update = 'Profile updated successfully'

    @Common().exception_handler
    def get_extract(self, params: GetProfileRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        return Response(Utils.success_response_data(
            message=self.data_get, data=AuthenticationUtils.profile_data(user),
        ))

    @Common().exception_handler
    def update_extract(self, params: UpdateProfileRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        changes = params.changed_fields()
        for field, value in changes.items():
            setattr(user, field, value)
        user.save(update_fields=list(changes))
        return Response(Utils.success_response_data(
            message=self.data_update, data=AuthenticationUtils.profile_data(user),
        ))
