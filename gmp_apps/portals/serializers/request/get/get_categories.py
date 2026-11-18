from typing import Any

from rest_framework import serializers

from gmp_apps.portals.dataclasses.request.get.get_categories import GetCategoriesRequest


class GetCategoriesRequestSerializer(serializers.Serializer):
    """No parameters: the list of categories in use is small and fixed-size."""

    def create(self, validated_data: dict[str, Any]) -> GetCategoriesRequest:
        return GetCategoriesRequest()
