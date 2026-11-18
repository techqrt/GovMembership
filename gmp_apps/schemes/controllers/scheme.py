from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole, has_admin_permission
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.schemes.serializers.request.delete.delete_scheme import DeleteSchemeRequestSerializer
from gmp_apps.schemes.serializers.request.get.get_scheme import GetSchemeRequestSerializer
from gmp_apps.schemes.serializers.request.get.get_tags import GetTagsRequestSerializer
from gmp_apps.schemes.serializers.response.get.get_scheme import SchemeResponseGetSerializer
from gmp_apps.schemes.serializers.response.get_all.get_all_scheme import SchemeResponseGetAllSerializer
from gmp_apps.schemes.serializers.response.get_all.get_all_tag import TagResponseGetAllSerializer
from gmp_apps.schemes.views.scheme import SchemesSchemeView

SCHEME_ID = [OpenApiParameter('scheme_id', int, required=True)]


class SchemesSchemeViewController:
    @extend_schema(
        description=(
            'Published government initiatives. Filter keys: department, schemeType, personType, caste (see tag/get_all for values). Sort keys: schemeId, title, department, '
            'updatedDateTime, createdDateTime. Search: title, department, description, eligibility, benefits, highlights.'
        ),
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=SchemeResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return SchemesSchemeView().get_all_extract(params=request.params)

    @extend_schema(
        description='Tags (scheme type, person type, caste) used by published schemes, with counts. Optional group filter.',
        parameters=[OpenApiParameter('group', str, enum=['scheme_type', 'person_type', 'caste'])],
        responses=SwaggerPage.response(response=TagResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetTagsRequestSerializer).validate
    def get_tags(request: Request) -> Response:
        return SchemesSchemeView().get_tags_extract(params=request.params)

    @extend_schema(
        description='One published scheme with every captured detail: eligibility, benefits, application procedure, documents, department, highlights, overview table, links (official website and important links), documents (brochure and guideline PDFs, served from this platform), contact details, additional sections, tags and images (served from this platform). Links and contact details are copied from the source and can go stale. Unpublished ids return 404.',
        parameters=SCHEME_ID,
        responses=SwaggerPage.response(response=SchemeResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetSchemeRequestSerializer).validate
    def get(request: Request) -> Response:
        return SchemesSchemeView().get_extract(params=request.params)

    @extend_schema(
        description=(
            'Admin only (needs the schemes.delete_scheme permission). Deletes the local record only, never anything on '
            'the source site, and stops the sync from re-importing that source URL until the exclusion is removed.'
        ),
        parameters=SCHEME_ID,
        responses=SwaggerPage.response(description=SchemesSchemeView().data_delete),
    )
    @api_view(['DELETE'])
    @permission_classes([has_admin_permission('schemes.delete_scheme')])
    @SerializerValidations(serializer=DeleteSchemeRequestSerializer).validate
    def delete(request: Request) -> Response:
        return SchemesSchemeView().delete_extract(params=request.params)
