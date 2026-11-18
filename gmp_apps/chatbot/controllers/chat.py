from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from gmp_apps.chatbot.serializers.request.create.ask import AskRequestSerializer
from gmp_apps.chatbot.serializers.request.get.get_status import GetStatusRequestSerializer
from gmp_apps.chatbot.serializers.response.create.ask import AskResponseSerializer
from gmp_apps.chatbot.serializers.response.get.get_status import StatusResponseSerializer
from gmp_apps.chatbot.throttles import ChatbotRateThrottle
from gmp_apps.chatbot.views.chat import ChatbotChatView
from gmp_apps.common.permissions import IsMemberRole
from gmp_apps.common.serializer_validations import SerializerValidations
from gmp_apps.common.swagger import SwaggerPage


class ChatbotChatViewController:
    @extend_schema(
        description=(
            'Ask the assistant a question, in any language. It answers ONLY from the administration\'s approved knowledge base: the reply '
            'is an approved answer (translated into the member\'s language when needed; numbers and links are checked against the approved '
            'text), with its curated links and app screens. When nothing approved matches, `type` is `no_answer` and the reply says so, with '
            'an action `contact_admin` to offer the Contact Admin form. Each question stands alone (no history). Limits: per-minute rate and '
            'a daily cap per member (429); 503 when the AI provider is unavailable. The assistant is not an authority: it never decides '
            'membership, eligibility or complaints.'
        ),
        request=AskRequestSerializer,
        responses=SwaggerPage.response(description='Answer prepared', response=AskResponseSerializer),
    )
    @api_view(['POST'])
    @permission_classes([IsMemberRole])
    @throttle_classes([ChatbotRateThrottle])
    @SerializerValidations(serializer=AskRequestSerializer).validate
    def ask(request: Request) -> Response:
        return ChatbotChatView().ask_extract(params=request.params)

    @extend_schema(
        description='Whether the assistant can be used right now (switched on, provider configured, at least one approved entry), and the question length limit.',
        responses=SwaggerPage.response(response=StatusResponseSerializer),
    )
    @api_view(['GET'])
    @permission_classes([IsMemberRole])
    @SerializerValidations(serializer=GetStatusRequestSerializer).validate
    def status(request: Request) -> Response:
        return ChatbotChatView().status_extract(params=request.params)
