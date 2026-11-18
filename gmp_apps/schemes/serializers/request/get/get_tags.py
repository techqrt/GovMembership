from typing import Any

from rest_framework import serializers

from gmp_apps.schemes.dataclasses.request.get.get_tags import GetTagsRequest
from gmp_apps.schemes.models.scheme_tag import TagGroup


class GetTagsRequestSerializer(serializers.Serializer):
    group = serializers.ChoiceField(choices=TagGroup.choices, required=False, default='')

    def create(self, validated_data: dict[str, Any]) -> GetTagsRequest:
        return GetTagsRequest(**validated_data)
