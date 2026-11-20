from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.get.get_id_card import GetIdCardRequest


class GetIdCardRequestSerializer(serializers.Serializer):
    """No parameters: the card is always the caller's own."""

    def create(self, validated_data: dict[str, Any]) -> GetIdCardRequest:
        return GetIdCardRequest()
