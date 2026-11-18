from rest_framework.response import Response

from gmp.config import Configurations
from gmp_apps.chatbot.dataclasses.request.create.ask import AskRequest
from gmp_apps.chatbot.dataclasses.request.get.get_status import GetStatusRequest
from gmp_apps.chatbot.service import ChatbotService, is_available
from gmp_apps.common.common import Common
from gmp_apps.common.utils import Utils


class ChatbotChatView:
    def __init__(self) -> None:
        self.data_ask = 'Answer prepared'
        self.data_get = 'Data fetched successfully'

    @Common().exception_handler
    def ask_extract(self, params: AskRequest) -> Response:
        """The member is identified by the token only. Nothing about them is sent to the AI provider."""
        return Response(Utils.success_response_data(message=self.data_ask, data=ChatbotService().ask(params.user_id, params.question)))

    @Common().exception_handler
    def status_extract(self, params: GetStatusRequest) -> Response:
        data = {'available': is_available(), 'maxQuestionChars': Configurations.chatbot_max_question_chars}
        return Response(Utils.success_response_data(message=self.data_get, data=data))
