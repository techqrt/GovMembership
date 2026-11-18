from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.refresh_token import RefreshTokenRequest


class RefreshTokenRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def create(self, validated_data: dict[str, Any]) -> RefreshTokenRequest:
        return RefreshTokenRequest(**validated_data)
