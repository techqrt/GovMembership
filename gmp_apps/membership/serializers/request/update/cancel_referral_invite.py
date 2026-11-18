from typing import Any

from rest_framework import serializers

from gmp_apps.membership.dataclasses.request.update.cancel_referral_invite import CancelReferralInviteRequest


class CancelReferralInviteRequestSerializer(serializers.Serializer):
    invite_id = serializers.IntegerField(min_value=1)

    def create(self, validated_data: dict[str, Any]) -> CancelReferralInviteRequest:
        return CancelReferralInviteRequest(**validated_data)
