from typing import Any

from rest_framework import serializers

from gmp_apps.dashboard.dataclasses.request.get.get_dashboard import GetDashboardRequest


class GetDashboardRequestSerializer(serializers.Serializer):
    """No parameters: the dashboard is always the caller's own."""

    def create(self, validated_data: dict[str, Any]) -> GetDashboardRequest:
        return GetDashboardRequest()
