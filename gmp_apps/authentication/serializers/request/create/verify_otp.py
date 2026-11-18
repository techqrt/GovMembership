from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.verify_otp import VerifyOtpRequest


class VerifyOtpRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)
    otp = serializers.CharField(max_length=10)

    def create(self, validated_data: dict[str, Any]) -> VerifyOtpRequest:
        return VerifyOtpRequest(**validated_data)
