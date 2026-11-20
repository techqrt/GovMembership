from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.create.create_permanent_application import (
    CreatePermanentApplicationRequest,
)


class CreatePermanentApplicationRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=2000)
    document_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=True, max_length=10)
    declaration_accepted = serializers.BooleanField(required=False, default=False)

    def create(self, validated_data: dict[str, Any]) -> CreatePermanentApplicationRequest:
        return CreatePermanentApplicationRequest(**validated_data)
