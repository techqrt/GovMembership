from typing import Any

from rest_framework import serializers

from gmp_apps.chatbot.dataclasses.request.create.ask import AskRequest


class AskRequestSerializer(serializers.Serializer):
    # The configured limit (CHATBOT_MAX_QUESTION_CHARS) is enforced with a friendly message in the service;
    # this only bounds how much text is even read.
    question = serializers.CharField(allow_blank=True, max_length=5000, trim_whitespace=False)

    def create(self, validated_data: dict[str, Any]) -> AskRequest:
        return AskRequest(**validated_data)
