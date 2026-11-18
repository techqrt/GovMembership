from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.logout import LogoutRequest


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def create(self, validated_data: dict[str, Any]) -> LogoutRequest:
        return LogoutRequest(**validated_data)
