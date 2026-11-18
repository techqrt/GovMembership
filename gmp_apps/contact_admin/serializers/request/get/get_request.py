from typing import Any

from rest_framework import serializers

from gmp_apps.contact_admin.dataclasses.request.get.get_request import GetRequestRequest


class GetRequestRequestSerializer(serializers.Serializer):
    request_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetRequestRequest:
        return GetRequestRequest(**validated_data)
