from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.portals.serializers.request.get.get_categories import GetCategoriesRequestSerializer
from gmp_apps.portals.serializers.request.get.get_portal import GetPortalRequestSerializer
from gmp_apps.portals.serializers.response.get.get_portal import PortalResponseGetSerializer
from gmp_apps.portals.serializers.response.get_all.get_all_portal import (
    CategoryResponseGetAllSerializer,
    PortalResponseGetAllSerializer,
)
from gmp_apps.portals.views.portal import PortalsPortalView

VISIT_NOTE = (
    'Official government grievance portals. This platform only lists them: open officialUrl in a new tab '
    '("Visit Portal"); complaints are registered, tracked and resolved on the official portal, never here.'
)


class PortalsPortalViewController:
    @extend_schema(
        description=(
            f'{VISIT_NOTE} Active portals of active categories only. Filter keys: categoryId, department. Sort keys: '
            'portalId, name, department, categoryName, createdDateTime. Search: name, description, department, category. '
            'Default order: category order, then portal order, then name.'
        ),
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=PortalResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return PortalsPortalView().get_all_extract(params=request.params)

    @extend_schema(
        description=f'One portal. {VISIT_NOTE} Inactive or unknown ids return 404.',
        parameters=[OpenApiParameter('portal_id', int, required=True)],
        responses=SwaggerPage.response(response=PortalResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetPortalRequestSerializer).validate
    def get(request: Request) -> Response:
        return PortalsPortalView().get_extract(params=request.params)

    @extend_schema(
        description='Categories that currently have at least one visible portal, with portal counts (for building filters).',
        responses=SwaggerPage.response(response=CategoryResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetCategoriesRequestSerializer).validate
    def get_categories(request: Request) -> Response:
        return PortalsPortalView().get_categories_extract(params=request.params)
