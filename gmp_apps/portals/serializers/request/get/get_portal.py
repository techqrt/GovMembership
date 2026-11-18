from typing import Any

from rest_framework import serializers

from gmp_apps.portals.dataclasses.request.get.get_portal import GetPortalRequest


class GetPortalRequestSerializer(serializers.Serializer):
    portal_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> GetPortalRequest:
        return GetPortalRequest(**validated_data)
