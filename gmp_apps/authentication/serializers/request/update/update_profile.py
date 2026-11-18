from typing import Any

from rest_framework import serializers

from gmp_apps.authentication.dataclasses.request.update.update_profile import UpdateProfileRequest
from gmp_apps.authentication.models.user import Gender


class UpdateProfileRequestSerializer(serializers.Serializer):
    """Editable profile fields only. Membership, role, identifiers and codes are not accepted."""

    full_name = serializers.CharField(max_length=150, required=False)
    date_of_birth = serializers.DateField(required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs:
            raise serializers.ValidationError('Provide at least one field to update')
        return attrs

    def create(self, validated_data: dict[str, Any]) -> UpdateProfileRequest:
        return UpdateProfileRequest(**validated_data)
