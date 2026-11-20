from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.membership.serializers.request.get.get_id_card import GetIdCardRequestSerializer
from gmp_apps.membership.serializers.response.get.get_id_card import IdCardResponseGetSerializer
from gmp_apps.membership.views.id_card import MembershipIdCardView


class MembershipIdCardViewController:
    @extend_schema(
        description=(
            'The caller\'s own digital ID card details, for the app to draw and share itself (image or PDF). Only the name, membership ID, '
            'level, member-since date and the profile photo link are returned; never Aadhaar, PAN, contact details or another member\'s data. '
            'There is no public link: the card is only readable by its owner.'
        ),
        responses=SwaggerPage.response(response=IdCardResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetIdCardRequestSerializer).validate
    def get(request: Request) -> Response:
        return MembershipIdCardView().get_extract(params=request.params)
