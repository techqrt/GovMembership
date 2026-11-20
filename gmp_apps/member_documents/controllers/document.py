from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.serializers.request.get_all import GetAllSerializer
from gmp_apps.common.serializers.response.api_response import ApiErrorSerializer
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.member_documents.serializers.request.create.create_document import CreateDocumentRequestSerializer
from gmp_apps.member_documents.serializers.request.get.get_document import GetDocumentRequestSerializer
from gmp_apps.member_documents.serializers.response.get.get_document import DocumentResponseGetSerializer
from gmp_apps.member_documents.serializers.response.get_all.get_all_document import DocumentResponseGetAllSerializer
from gmp_apps.member_documents.throttles import DocumentUploadThrottle
from gmp_apps.member_documents.views.document import MemberDocumentView


class MemberDocumentViewController:
    @extend_schema(
        description=(
            'Upload one of your own documents (multipart/form-data: document_type, file, optional label). Members only, '
            'for yourself only. Any file type is accepted EXCEPT scripts, web pages, SVG and executables (400). The file is '
            'checked by its bytes, stored privately under a random name and can only be read back by you and authorised '
            'admins. Limits (size, files in total, files per type, uploads per hour) come from the server configuration; '
            'a profile photo must be an image and you can have one.'
        ),
        request={'multipart/form-data': CreateDocumentRequestSerializer},
        responses=SwaggerPage.response(description=MemberDocumentView().data_create, response=DocumentResponseGetSerializer),
    )
    @api_view(['POST'])
    @parser_classes([MultiPartParser])
    @permission_classes([IsMemberRole])
    @throttle_classes([DocumentUploadThrottle])
    @SerializerValidations(serializer=CreateDocumentRequestSerializer).validate
    def create(request: Request) -> Response:
        return MemberDocumentView().create_extract(params=request.params)

    @extend_schema(
        description='One of your own documents (404 for anyone else\'s). Use downloadUrl, with your Bearer token, to fetch the file.',
        parameters=[OpenApiParameter('document_id', int, required=True)],
        responses=SwaggerPage.response(response=DocumentResponseGetSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetDocumentRequestSerializer).validate
    def get(request: Request) -> Response:
        return MemberDocumentView().get_extract(params=request.params)

    @extend_schema(
        description='Your own documents. Filter keys: documentType. Sort keys: documentId, documentType, createdDateTime, sizeBytes. Search: label and file name.',
        parameters=SwaggerPage.get_all_parameters(),
        responses=SwaggerPage.response(response=DocumentResponseGetAllSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetAllSerializer).validate
    def get_all(request: Request) -> Response:
        return MemberDocumentView().get_all_extract(params=request.params)

    @extend_schema(
        description='Delete one of your own documents and its stored file (404 for anyone else\'s).',
        parameters=[OpenApiParameter('document_id', int, required=True)],
        responses=SwaggerPage.response(description=MemberDocumentView().data_delete),
    )
    @api_view(['DELETE'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetDocumentRequestSerializer).validate
    def delete(request: Request) -> Response:
        return MemberDocumentView().delete_extract(params=request.params)

    @extend_schema(
        description=(
            'Download one of your own files (404 for anyone else\'s). Always sent as an attachment with '
            'Content-Type application/octet-stream and X-Content-Type-Options: nosniff, so it can be saved but never '
            'run or embedded by the browser. Fetch it with your Bearer token and save it as a blob.'
        ),
        parameters=[OpenApiParameter('document_id', int, required=True)],
        responses={200: OpenApiTypes.BINARY, 401: ApiErrorSerializer, 403: ApiErrorSerializer, 404: ApiErrorSerializer},
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetDocumentRequestSerializer).validate
    def download(request: Request) -> Response:
        return MemberDocumentView().download_extract(params=request.params)
