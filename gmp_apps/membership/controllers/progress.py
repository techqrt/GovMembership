from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.membership.serializers.request.get.get_progress import GetProgressRequestSerializer
from gmp_apps.membership.serializers.response.get.get_progress import ProgressResponseGetSerializer
from gmp_apps.membership.views.progress import MembershipProgressView


class MembershipProgressViewController:
    @extend_schema(
        description='Own membership level, referral code and link, referral progress towards Active, and Permanent application state.',
        responses=SwaggerPage.response(response=ProgressResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetProgressRequestSerializer).validate
    def get(request: Request) -> Response:
        return MembershipProgressView().get_extract(params=request.params)
