from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.create.resend_otp import ResendOtpRequest


class ResendOtpRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)

    def create(self, validated_data: dict[str, Any]) -> ResendOtpRequest:
        return ResendOtpRequest(**validated_data)
