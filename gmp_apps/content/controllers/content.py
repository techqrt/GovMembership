from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.content.serializers.request.get.get_categories import GetCategoriesRequestSerializer
from gmp_apps.content.serializers.request.get.get_content import GetContentRequestSerializer
from gmp_apps.content.serializers.response.get.get_content import ContentResponseGetSerializer
from gmp_apps.content.serializers.response.get_all.get_all_content import (
    CategoryResponseGetAllSerializer,
    ContentResponseGetAllSerializer,
)
from gmp_apps.content.views.content import ContentItemView

VISIBILITY_NOTE = (
    'Only content the caller may read is returned: published, already live, not expired, in an active category and '
    'allowed for the caller\'s current membership level. Anything else (including content restricted to a higher level) '
    'is not returned and is indistinguishable from missing content.'
)


class ContentItemViewController:
    @extend_schema(
        description=(
            f'Posts, announcements, videos, tutorials and organisation updates (summaries; the body is on get). {VISIBILITY_NOTE} '
            'Filter keys: type (post, announcement, video, tutorial, org_update), categoryId. Sort keys: contentId, title, type, '
            'publishedDateTime, createdDateTime. Search: title, summary, body, category. Default order: pinned first, then newest.'
        ),
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=ContentResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return ContentItemView().get_all_extract(params=request.params)

    @extend_schema(
        description=f'One content item with its plain-text body. Videos are links to an allowed video host (never hosted here). {VISIBILITY_NOTE}',
        parameters=[OpenApiParameter('content_id', int, required=True)],
        responses=SwaggerPage.response(response=ContentResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetContentRequestSerializer).validate
    def get(request: Request) -> Response:
        return ContentItemView().get_extract(params=request.params)

    @extend_schema(
        description=f'Categories that currently hold content the caller may read, with counts (for filters). {VISIBILITY_NOTE}',
        responses=SwaggerPage.response(response=CategoryResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetCategoriesRequestSerializer).validate
    def get_categories(request: Request) -> Response:
        return ContentItemView().get_categories_extract(params=request.params)
