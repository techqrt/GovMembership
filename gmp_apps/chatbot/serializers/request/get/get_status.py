from typing import Any

from rest_framework import serializers

from gmp_apps.chatbot.dataclasses.request.get.get_status import GetStatusRequest


class GetStatusRequestSerializer(serializers.Serializer):
    def create(self, validated_data: dict[str, Any]) -> GetStatusRequest:
        return GetStatusRequest()
