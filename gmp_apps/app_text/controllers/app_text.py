from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.app_text.serializers.request.get_all.get_all_app_text import GetAllAppTextRequestSerializer
from gmp_apps.app_text.serializers.response.get_all.get_all_app_text import AppTextResponseGetAllSerializer
from gmp_apps.app_text.throttles import AppTextThrottle
from gmp_apps.app_text.views.app_text import AppTextAppTextView
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage


class AppTextAppTextViewController:
    @extend_schema(
        description=(
            'All app text strings in one language, as a key-to-text map, for the app to show Hindi or English. Public, because the login and '
            'register screens need it before sign-in; it holds only interface wording an admin wrote, never member data. Send the member\'s '
            'saved `appLanguage` as `language` (en or hi, default en). A string with no Hindi text comes back in English.'
        ),
        parameters=[OpenApiParameter('language', str, enum=['en', 'hi'], description='Default en')],
        responses=SwaggerPage.response(response=AppTextResponseGetAllSerializer, authenticated=False),
    )
    @api_view(['GET'])
    @permission_classes([AllowAny])
    @throttle_classes([AppTextThrottle])
    @SerializerValidations(serializer=GetAllAppTextRequestSerializer).validate
    def get_all(request: Request) -> Response:
        return AppTextAppTextView().get_all_extract(params=request.params)
