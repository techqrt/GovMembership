from typing import Any

from rest_framework import serializers

from gmp_apps.schemes.dataclasses.request.get.get_scheme import GetSchemeRequest


class GetSchemeRequestSerializer(serializers.Serializer):
    scheme_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetSchemeRequest:
        return GetSchemeRequest(**validated_data)
