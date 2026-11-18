from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.login import LoginRequest


class LoginRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def create(self, validated_data: dict[str, Any]) -> LoginRequest:
        return LoginRequest(**validated_data)
