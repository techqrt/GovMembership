from rest_framework.response import Response

from gmp_apps.authentication.models import User
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils
from gmp_apps.membership.dataclasses.request.get.get_id_card import GetIdCardRequest
from gmp_apps.membership.utils import MembershipUtils


class MembershipIdCardView:
    def __init__(self) -> None:
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def get_extract(self, params: GetIdCardRequest) -> Response:
        user = User.objects.get(user_id=params.user_id)
        return Response(Utils.success_response_data(message=self.data_get, data=MembershipUtils.id_card_data(user)))
