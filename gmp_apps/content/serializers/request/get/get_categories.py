from typing import Any

from rest_framework import serializers

from gmp_apps.content.dataclasses.request.get.get_categories import GetCategoriesRequest


class GetCategoriesRequestSerializer(serializers.Serializer):
    """No parameters: categories are derived from the caller's own membership level."""

    def create(self, validated_data: dict[str, Any]) -> GetCategoriesRequest:
        return GetCategoriesRequest()
