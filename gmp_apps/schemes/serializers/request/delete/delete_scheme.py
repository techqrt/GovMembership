from typing import Any

from rest_framework import serializers

from gmp_apps.schemes.dataclasses.request.delete.delete_scheme import DeleteSchemeRequest


class DeleteSchemeRequestSerializer(serializers.Serializer):
    scheme_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> DeleteSchemeRequest:
        return DeleteSchemeRequest(**validated_data)
