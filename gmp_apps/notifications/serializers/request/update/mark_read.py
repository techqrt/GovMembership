from typing import Any

from rest_framework import serializers

from gmp_apps.notifications.dataclasses.request.update.mark_read import MarkReadRequest


class MarkReadRequestSerializer(serializers.Serializer):
    notification_id = serializers.IntegerField(min_value=1, required=False)
    mark_all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get('notification_id')) == bool(attrs.get('mark_all')):
            raise serializers.ValidationError('Send either notification_id or mark_all=true')
        return attrs

    def create(self, validated_data: dict[str, Any]) -> MarkReadRequest:
        return MarkReadRequest(**validated_data)
