from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.membership.serializers.request.create.create_referral_invite import (
    CreateReferralInviteRequestSerializer,
)
from gmp_apps.membership.serializers.request.update.cancel_referral_invite import CancelReferralInviteRequestSerializer
from gmp_apps.membership.serializers.response.get.get_referral_invite import ReferralInviteResponseGetSerializer
from gmp_apps.membership.serializers.response.get_all.get_all_referral_invite import (
    ReferralInviteResponseGetAllSerializer,
)
from gmp_apps.membership.views.referral_invite import MembershipReferralInviteView


class MembershipReferralInviteViewController:
    @extend_schema(
        description=(
            'Refer a person (name plus email and/or mobile). No message is sent; share the returned referral link. '
            'When they register with that contact the referral is linked automatically. An explicit referral code '
            'at registration wins. Counts toward Active only after they verify a contact.'
        ),
        request=CreateReferralInviteRequestSerializer,
        responses=SwaggerPage.response(
            description=MembershipReferralInviteView().data_create, response=ReferralInviteResponseGetSerializer,
        ),
    )
    @api_view(['POST'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=CreateReferralInviteRequestSerializer).validate
    def create(request: Request) -> Response:
        return MembershipReferralInviteView().create_extract(params=request.params)

    @extend_schema(
        description='Cancel one of your own open referrals. Expired, registered or already cancelled ones return 400; someone else\'s id returns 404.',
        parameters=[OpenApiParameter('invite_id', int, required=True)],
        responses=SwaggerPage.response(
            description=MembershipReferralInviteView().data_cancel, response=ReferralInviteResponseGetSerializer,
        ),
    )
    @api_view(['DELETE'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=CancelReferralInviteRequestSerializer).validate
    def delete(request: Request) -> Response:
        return MembershipReferralInviteView().cancel_extract(params=request.params)

    @extend_schema(
        description='People you referred by name/contact. Filter keys: status. Sort keys: inviteId, fullName, status, createdDateTime.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=ReferralInviteResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return MembershipReferralInviteView().get_all_extract(params=request.params)
