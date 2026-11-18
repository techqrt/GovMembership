from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.get.get_permanent_application import GetPermanentApplicationRequest


class GetPermanentApplicationRequestSerializer(serializers.Serializer):
    application_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetPermanentApplicationRequest:
        return GetPermanentApplicationRequest(**validated_data)
