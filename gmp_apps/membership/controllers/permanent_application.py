from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.membership.serializers.request.create.create_permanent_application import (
    CreatePermanentApplicationRequestSerializer,
)
from gmp_apps.membership.serializers.request.get.get_permanent_application import (
    GetPermanentApplicationRequestSerializer,
)
from gmp_apps.membership.serializers.response.get.get_permanent_application import PermanentApplicationResponseGetSerializer
from gmp_apps.membership.serializers.response.get_all.get_all_permanent_application import (
    PermanentApplicationResponseGetAllSerializer,
)
from gmp_apps.membership.views.permanent_application import MembershipPermanentApplicationView

APPLICATION_ID = [OpenApiParameter('application_id', int, required=True)]


class MembershipPermanentApplicationViewController:
    @extend_schema(
        description='Apply for Permanent membership. Only Active members, one pending application at a time. Approval is by an admin.',
        request=CreatePermanentApplicationRequestSerializer,
        responses=SwaggerPage.response(
            description=MembershipPermanentApplicationView().data_create, response=PermanentApplicationResponseGetSerializer,
        ),
    )
    @api_view(['POST'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=CreatePermanentApplicationRequestSerializer).validate
    def create(request: Request) -> Response:
        return MembershipPermanentApplicationView().create_extract(params=request.params)

    @extend_schema(
        description='Get one of your own Permanent applications (404 for anyone else\'s).',
        parameters=APPLICATION_ID,
        responses=SwaggerPage.response(response=PermanentApplicationResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetPermanentApplicationRequestSerializer).validate
    def get(request: Request) -> Response:
        return MembershipPermanentApplicationView().get_extract(params=request.params)

    @extend_schema(
        description='Own Permanent applications. Filter keys: status. Sort keys: applicationId, status, createdDateTime.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=PermanentApplicationResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return MembershipPermanentApplicationView().get_all_extract(params=request.params)
