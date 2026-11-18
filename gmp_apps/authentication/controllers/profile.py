from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.authentication.serializers.request.get.get_profile import GetProfileRequestSerializer
from gmp_apps.authentication.serializers.request.update.update_profile import UpdateProfileRequestSerializer
from gmp_apps.authentication.serializers.response.get.get_profile import ProfileResponseGetSerializer
from gmp_apps.authentication.views.profile import AuthenticationProfileView
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage


class AuthenticationProfileViewController:
    @extend_schema(
        description='Get the caller\'s own profile, membership ID, level and referral code.',
        responses=SwaggerPage.response(response=ProfileResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsAuthenticated])
    @SerializerValidations(serializer=GetProfileRequestSerializer).validate
    def get(request: Request) -> Response:
        return AuthenticationProfileView().get_extract(params=request.params)

    @extend_schema(
        description='Update the caller\'s editable profile fields. Membership level, role, identifiers and codes cannot be changed here.',
        request=UpdateProfileRequestSerializer,
        responses=SwaggerPage.response(
            description=AuthenticationProfileView().data_update, response=ProfileResponseGetSerializer,
        ),
    )
    @api_view(['PUT'])
    @permission_classes([IsAuthenticated])
    @SerializerValidations(serializer=UpdateProfileRequestSerializer).validate
    def update(request: Request) -> Response:
        return AuthenticationProfileView().update_extract(params=request.params)
