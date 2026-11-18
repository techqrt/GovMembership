from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.get.get_profile import GetProfileRequest


class GetProfileRequestSerializer(serializers.Serializer):
    """No parameters: the profile is always the caller's own (no user id is accepted)."""

    def create(self, validated_data: dict[str, Any]) -> GetProfileRequest:
        return GetProfileRequest()
