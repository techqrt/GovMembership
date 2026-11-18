from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.forgot_password import ForgotPasswordRequest


class ForgotPasswordRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)

    def create(self, validated_data: dict[str, Any]) -> ForgotPasswordRequest:
        return ForgotPasswordRequest(**validated_data)
