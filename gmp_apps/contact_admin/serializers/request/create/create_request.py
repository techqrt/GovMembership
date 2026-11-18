from typing import Any

from rest_framework import serializers

from gmp.constants import Constants
from gmp_apps.contact_admin.dataclasses.request.create.create_request import CreateRequestRequest
from gmp_apps.contact_admin.models import ContactCategory


class CreateRequestRequestSerializer(serializers.Serializer):
    category_id = serializers.IntegerField(min_value=1)
    subject = serializers.CharField(min_length=3, max_length=200)
    description = serializers.CharField(min_length=10, max_length=5000)

    def validate_category_id(self, value: int) -> int:
        if not ContactCategory.objects.filter(category_id=value, is_active=True).exists():
            raise serializers.ValidationError(Constants.contact_bad_category)
        return value

    def create(self, validated_data: dict[str, Any]) -> CreateRequestRequest:
        return CreateRequestRequest(**validated_data)
