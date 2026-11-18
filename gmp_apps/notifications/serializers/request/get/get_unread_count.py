from typing import Any

from rest_framework import serializers

from gmp_apps.notifications.dataclasses.request.get.get_unread_count import GetUnreadCountRequest


class GetUnreadCountRequestSerializer(serializers.Serializer):
    def create(self, validated_data: dict[str, Any]) -> GetUnreadCountRequest:
        return GetUnreadCountRequest()
