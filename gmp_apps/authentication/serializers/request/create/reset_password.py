from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.reset_password import ResetPasswordRequest


class ResetPasswordRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)
    otp = serializers.CharField(max_length=10)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        validate_password(value)
        return value

    def create(self, validated_data: dict[str, Any]) -> ResetPasswordRequest:
        return ResetPasswordRequest(**validated_data)
