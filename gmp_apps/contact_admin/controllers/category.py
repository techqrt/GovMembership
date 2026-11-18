from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.contact_admin.serializers.response.get_all.get_all_request import CategoryResponseGetAllSerializer
from gmp_apps.contact_admin.views.category import ContactAdminCategoryView


class ContactAdminCategoryViewController:
    @extend_schema(
        description='Active categories to choose from when contacting the administration. Sort keys: categoryId, name.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=CategoryResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return ContactAdminCategoryView().get_all_extract(params=request.params)
