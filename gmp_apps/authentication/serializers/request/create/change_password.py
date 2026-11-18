from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.change_password import ChangePasswordRequest


class ChangePasswordRequestSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        validate_password(value)
        return value

    def create(self, validated_data: dict[str, Any]) -> ChangePasswordRequest:
        return ChangePasswordRequest(**validated_data)
