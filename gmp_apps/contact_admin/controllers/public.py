from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage
from gmp_apps.common.throttles import ContactCategoryThrottle, ContactSubmitThrottle
from gmp_apps.contact_admin.serializers.request.create.create_public_request import CreatePublicRequestRequestSerializer
from gmp_apps.contact_admin.serializers.response.get.get_public_category import PublicCategoryResponseGetAllSerializer
from gmp_apps.contact_admin.views.public import ContactPublicView


class ContactPublicRequestViewController:
    @extend_schema(
        description=(
            'Public Contact Us form (no login). Send problem_type (the topic name: Membership, Schemes, Complaints or Any other; category_id, the topic number from the topics list, also works and must match if both are sent), full_name, at least one of email or '
            'mobileNumber, description (10 to 5000 characters, no HTML) and an optional subject (left empty if not sent). '
            'Keep the field `website` in the form but hidden and empty: it is a trap for bots, and a filled one is dropped '
            'silently with the same success answer. No attachments. Rate limited per IP (429 when exceeded). The answer is only '
            'a "received" message: nothing is returned that could be looked up later. The administration replies by the email or '
            'mobile number given; nothing is sent automatically. "Complaints" is only a topic label: complaints are not '
            'registered, tracked or resolved on this platform.'
        ),
        request=CreatePublicRequestRequestSerializer,
        responses=SwaggerPage.response(description=ContactPublicView().data_create, authenticated=False),
    )
    @api_view(['POST'])
    @authentication_classes([])   # a visitor with an old or broken token must not be refused: no login is used here
    @permission_classes([AllowAny])
    @throttle_classes([ContactSubmitThrottle])
    @SerializerValidations(serializer=CreatePublicRequestRequestSerializer).validate
    def create(request: Request) -> Response:
        return ContactPublicView().create_extract(params=request.params)


class ContactPublicCategoryViewController:
    @extend_schema(
        description='Public. The Contact Us topics for the dropdown, in order: Membership, Schemes, Complaints, Any other. Names and ids only.',
        responses=SwaggerPage.response(response=PublicCategoryResponseGetAllSerializer, authenticated=False),
    )
    @api_view(['GET'])
    @authentication_classes([])
    @permission_classes([AllowAny])
    @throttle_classes([ContactCategoryThrottle])
    def get_all(request: Request) -> Response:
        return ContactPublicView().get_all_extract()
