from django.urls import path

from gmp_apps.chatbot.controllers.chat import ChatbotChatViewController as Chat

urlpatterns = [
    path('ask/', Chat.ask, name='create_chatbot_ask'),
    path('status/', Chat.status, name='get_chatbot_status'),
]
