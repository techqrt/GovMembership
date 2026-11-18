from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.create.create_permanent_application import (
    CreatePermanentApplicationRequest,
)


class CreatePermanentApplicationRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=2000)

    def create(self, validated_data: dict[str, Any]) -> CreatePermanentApplicationRequest:
        return CreatePermanentApplicationRequest(**validated_data)
