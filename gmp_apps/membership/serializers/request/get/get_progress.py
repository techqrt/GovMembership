from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.get.get_progress import GetProgressRequest


class GetProgressRequestSerializer(serializers.Serializer):
    """No parameters: progress is always the caller's own."""

    def create(self, validated_data: dict[str, Any]) -> GetProgressRequest:
        return GetProgressRequest()
