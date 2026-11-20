from typing import Any

from rest_framework import serializers

from gmp_apps.app_text.dataclasses.request.get_all.get_all_app_text import GetAllAppTextRequest
from gmp_apps.app_text.models import SUPPORTED_LANGUAGES


class GetAllAppTextRequestSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=SUPPORTED_LANGUAGES, required=False, default='en')

    def create(self, validated_data: dict[str, Any]) -> GetAllAppTextRequest:
        return GetAllAppTextRequest(language=validated_data['language'])
