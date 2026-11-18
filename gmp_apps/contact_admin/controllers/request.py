from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.contact_admin.serializers.request.create.create_request import CreateRequestRequestSerializer
from gmp_apps.contact_admin.serializers.request.get.get_request import GetRequestRequestSerializer
from gmp_apps.contact_admin.serializers.response.get.get_request import RequestResponseGetSerializer
from gmp_apps.contact_admin.serializers.response.get_all.get_all_request import RequestResponseGetAllSerializer
from gmp_apps.contact_admin.views.request import ContactAdminRequestView


class ContactAdminRequestViewController:
    @extend_schema(
        description=(
            'Contact the administration: category, subject, description. Members only. Limits: open requests per member '
            'and requests per day. The reply and status are set by an admin.'
        ),
        request=CreateRequestRequestSerializer,
        responses=SwaggerPage.response(description=ContactAdminRequestView().data_create, response=RequestResponseGetSerializer),
    )
    @api_view(['POST'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=CreateRequestRequestSerializer).validate
    def create(request: Request) -> Response:
        return ContactAdminRequestView().create_extract(params=request.params)

    @extend_schema(
        description='One of your own requests with the admin reply (404 for anyone else\'s).',
        parameters=[OpenApiParameter('request_id', int, required=True)],
        responses=SwaggerPage.response(response=RequestResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetRequestRequestSerializer).validate
    def get(request: Request) -> Response:
        return ContactAdminRequestView().get_extract(params=request.params)

    @extend_schema(
        description='Your own requests. Filter keys: status, categoryId. Sort keys: requestId, status, subject, createdDateTime. Search: subject and description.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=RequestResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return ContactAdminRequestView().get_all_extract(params=request.params)
