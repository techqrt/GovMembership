from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.membership.serializers.response.get_all.get_all_referral import ReferralResponseGetAllSerializer
from gmp_apps.membership.views.referral import MembershipReferralView


class MembershipReferralViewController:
    @extend_schema(
        description='Own referrals (first name and status only). Filter keys: status. Sort keys: referralId, status, createdDateTime.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=ReferralResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return MembershipReferralView().get_all_extract(params=request.params)
