from typing import Any

from rest_framework import serializers

from gmp_apps.content.dataclasses.request.get.get_content import GetContentRequest


class GetContentRequestSerializer(serializers.Serializer):
    content_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetContentRequest:
        return GetContentRequest(**validated_data)
