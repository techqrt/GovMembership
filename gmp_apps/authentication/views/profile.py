from rest_framework.response import Response

from gmp_apps.authentication.dataclasses.request.get.get_profile import GetProfileRequest
from gmp_apps.authentication.dataclasses.request.update.update_profile import UpdateProfileRequest
from gmp_apps.authentication.models import User
from gmp_apps.authentication.utils import AuthenticationUtils
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils
from gmp_apps.contact_admin.models import ContactRequest
from gmp_apps.contact_admin.models.contact_request import OPEN_STATUSES
from gmp_apps.membership.models import PermanentApplication
from gmp_apps.membership.models.permanent_application import ApplicationStatus


class AuthenticationProfileView:
    """Profile of the caller only: the user is taken from the token, never from a request parameter."""

    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'
        self.data_update = 'Profile updated successfully'

    @Common().exception_handler
    def get_extract(self, params: GetProfileRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        data = {**AuthenticationUtils.profile_data(user), 'activeApplications': self.active_applications(user)}
        return Response(Utils.success_response_data(message=self.data_get, data=data))

    @staticmethod
    def active_applications(user: User) -> dict[str, int]:
        """The caller's own unfinished items, for the profile badge. Read-only, computed on every read, nothing stored."""
        permanent = PermanentApplication.objects.filter(user=user, status=ApplicationStatus.PENDING).count()
        support = ContactRequest.objects.filter(user=user, status__in=OPEN_STATUSES).count()
        return {'permanent': permanent, 'support': support, 'total': permanent + support}

    @Common().exception_handler
    def update_extract(self, params: UpdateProfileRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        changes = params.changed_fields()
        columns: list[str] = []
        for kind in ('aadhaar', 'pan'):
            value = changes.pop(f'{kind}_number', None)
            if value is not None:   # '' clears; a masked echo was already dropped by the serializer
                columns += user.set_government_id(kind, str(value))
        for field, value in changes.items():
            setattr(user, field, value)
        user.save(update_fields=[*changes, *columns])
        return Response(Utils.success_response_data(
            message=self.data_update, data=AuthenticationUtils.profile_data(user),
        ))
